"""Plans and steps — the live state of one job, held where a lead can show it.

The design is `design/PLANS-AND-STEPS.md`; this is the state model, the verbs that make a
plan (`create`, `template use`, `name-step`), the verbs that read one (`list`, `show`,
`changelog`, `library`, `validate`), the three small ones worth typing while a job runs
(`tick`, `skip`, `note`), the two things that are READ every time a plan is displayed
and written down nowhere — a step owner's status, and the plan's own condition — and the
instruction that says when to make a plan at all (`guide`). What is still not here is
anything that decides for itself: nothing in this file blocks, merges, tears down or
watches for a human's answer, and the section on gates below says why that is the design
rather than a gap.

THE FILE IS THE INTERFACE, and the verb list above is short because of it. An owner, a
gate, a skip and its reason, a checkpoint, a reworked step were each a verb once and each
wrote ONE FIELD; what a lead does to a plan is shape it, which is what an editor is for,
and a verb per field was a surface nobody could hold in their head to do that worse.
`create` and `template use` print the path of the file they made, the file is edited, and
`validate` says what the edit broke. What those verbs did enforce is not gone with them —
see `_wrong`, where their three refusals became warnings that reach a hand-edit too, which
is more than the verbs ever covered.

The records
-----------

    plan  {"id": "p-1", "workspace": "task-guardrails-build", "workspace_from": "agent",
           "checkout": "/…/worktrees/switchboard/task-guardrails-build", "title": "…",
           "display": "…", "next_step": 4, "steps": [...], "changelog": [...],
           "notes": [...], "created_by": "lead", "created_at": 1754570000}

    step  {"id": "step-1", "name": "…", "display": null, "def": null, "obliged_by": null,
           "progress": "open", "why": null, "gate": null, "output": null, "owner": null,
           "tries": 1, "notes": [], "deps": [], "root": false, "checkpoints": []}

`progress` is an OPEN VOCABULARY, exactly as `todo`'s `state` is: `open` is what `create`
writes and `done`/`skipped` are what the lifecycle verbs will, but nothing here is an enum
and a lead that wants `progress: waiting on Andrew` gets it without a release. The design
says the agent is the interpreter and there is no schema to satisfy, so a step carrying a
field this file has never heard of is a feature and not corruption — `_step()` fills in the
fields the design names and leaves everything else alone, and EVERY RENDERING SHOWS IT:
`--json` and `--markdown` because neither knows a schema, and the terminal view because
`_step_lines` draws what it has no name for on a line of its own under the step — a scalar
one, that being what a line holds; a list or an object is left to `--json`, which is the
shape that can carry one. A promise kept in two renderings out of three was one the third
made a liar of.

Moving a step
-------------

`tick` is the one verb that writes progress, and what it writes is `done`. Nothing infers
it, `sb done` does not touch it, no verb moves it as a side effect of doing something else,
and nothing in this file ever writes `done` on a step's behalf — which is the design's
first rule about progress and the reason `tick` exists as a verb at all when the field
beside it is edited by hand. The other two moves are the file: `skipped` with the reason in
`why`, and back to `open` with `tries` bumped for a step being redone.

Complete-or-skipped-but-never-both is structural rather than checked: `progress` is ONE
string, so a skip written over a ticked step replaces the tick instead of joining it. What
overwrites what another agent wrote is a correction, and the changelog is what says which
it was — a `tick` records the progress it moved a step FROM, and a hand-edit says so in the
entry its author appends.

`why` is the reason for the step's current progress, kept on the step so that a skipped step
renders with the reason beside it rather than twenty lines below in the changelog. The
design's "a skip is a state rather than an absence" is only true if the reason is visible
where the state is. It is overwritten by whatever changes progress next, so a step ticked
after a skip does not keep the sentence explaining why it was skipped.

`tries` is rework: re-entering a step bumps the count and puts progress back to `open`.
Repetition is a number on the step and never an edge, so nothing here creates a cycle to
represent a second attempt. Nothing downstream is un-ticked either — the design makes that
the lead's judgement, and a rule here would either merge unreviewed work or throw away a
day of good review.

`checkpoints` are references — a path, a URL, an id — and never content. A ref with a line
break in it is WARNED ABOUT (`_wrong`), because the only way one gets there is somebody
pasting the brief instead of pointing at it, and a plan holding a copy of a brief is a
second copy that goes stale.

`output` is the step's own finished output, and it is the ONE field in this file that is
content rather than a reference — it is that because the whole point of it is being
DUMPED. A change approval that a human approved has to reach the pull request in full, and
a ref does not dump: `create-pr` posts `show --markdown` and whoever reads the PR gets
whatever that carries. So the text is kept on the step, multi-line, and `--markdown`
renders it as a blockquote block rather than flattening it to one line (`_BLOCK`). Written
BY HAND by the agent that did the step, as it ticks, like `gate` and unlike `tick`: no
verb writes it, because a verb would have to be exempted from both doors `_cap` keeps —
`MAX_TEXT` and the control character — and an approved contract is longer than one and
made of the other. REPLACED and never appended: a rejected contract is overwritten by the
redone one, and what records the loop is `tries` and the changelog, which is exactly why
this is not a note.

Gates
-----

`gate` is a step's exit condition when that condition is A HUMAN: the sentence saying what
they have to answer before this step is finished. It is a FIELD ON A STEP — written into
the file, with no verb of its own — and never a step of its own, which is the design's
first rule about gates and the one thing here not to get wrong. A design step ending in
"no implementation until they confirm" needs no second step for the confirmation; what
shows on a board, what carries a skip and its reason, and what an obligation attaches to
is always the step whose exit condition the gate is. Open vocabulary like `progress`, for
the same reason: the agent is the interpreter, and a job with a gate this file has never
heard of gets it without a release.

Nothing here waits, blocks, merges or tears anything down, and that boundary is the whole
of the mechanism. The PROCEDURE at a gate is prose an agent follows, kept with the thing
that gates rather than in one list of gates — a definition's own `about` for a named step,
`sb presets design-gate` for the bullet format such a message is written in — and the agent
runs it with the tools it already has. `guide` does not carry it and does not name the
gates: an agent reaches a gate by reaching the step that has one, so the step is where it
will look. This file's entire job is to REPRESENT the gate: to hold the sentence, to
render it, and to make sure a gate cannot be got past without leaving a
mark. A plugin that shelled out to `gh` or `git merge` on a plan's behalf would be the
evaluator this design deliberately does not have, and it would be one on the only path
where being wrong lands a merge nobody asked for.

Which is why NOTHING here clears a gate. At a gate the owning agent blocks, the step
renders its owner as blocked — read off `sb status` at the instant of drawing, like every
other liveness fact here, and stored nowhere — and the human answering that agent clears
both the block and the gate. A command to clear one through the plan would make the plan a
control surface, and the design says plainly that Andrew talks only to agents and never
edits a plan. `tick` is what records that the step then finished, by the agent that was
there; a skip with its reason is the other way past, for a change too small to be worth a
block. Both leave a mark. Deleting the sentence from the file is a third way, and it is the
one thing the record cannot show — which is what the changelog entry an editor's author
appends is for, and why a gate is corrected rather than emptied.

A gate does not belong on a step that is already DONE, and a plan carrying one is drawn
red (`_wrong`). The design allows a plan to be created with some of its steps already
complete but not a step whose exit condition is a gate: a gate exists to be reached before
the work it guards, so a plan authored after the fact does not get to mark one already
passed. If the work is genuinely past that point the step is skipped with the reason —
visible — rather than born complete, which is not. A SKIPPED step may carry one, and that
is the same rule from the other side: it is exactly how a lead replacing a dead one records
a gate the previous plan cleared.

`deps` are what a step comes after: data the lead reads, and this file's only interest in
them is that they are storable and renderable. Written into the file like every other field
a lead shapes a plan with — the verb that wrote one is gone, because it set one field and
what it bought over an edit was the changelog entry nothing asks for any more. Nothing
traverses them, waits on them, orders anything by them or refuses a cycle in them — a join
waits because the lead does not start it. An edge naming a step that is not there is a typo
the file cannot catch at the door any more; what catches it is `validate` and the board,
which draw the plan the edge actually describes.

Reassigning tells nobody. `owner` is a name written onto a step and nothing more: the plan
never pushes to a running agent, and the old owner learns it lost the step from its parent
or not at all. Two agents believing they own one step is the collision the design accepts.

The catalogue
-------------

A step is either invented on the fly — `create --step`, a hand-written step, a name and
nothing else
— or NAMED from the library, which is `library/*.json` shipped beside this file. Both are
first class, and the difference is one field: a named step stores `def` and leaves `name`
null, and the text is resolved out of the library every time the plan is rendered.

That is the whole point and the one thing not to get wrong. A named step is a LINK plus its
own run object: the plan owns progress, owner, tries, notes, checkpoints and deps, and the
library owns the name, the composition and the obligations. Nothing is snapshotted, so
editing a definition reaches every plan naming it — live ones included — which is what the
design buys by saying steps are units and there is little about a definition to change. A
lead that wants something else writes an on-the-fly step; there is no forking a link, and no
verb here edits the library, because the library is files and files are edited in an editor.

A step also carries a `display` — a name AS SHORT AS POSSIBLE, `scan code` where the name is
"list every claim the document makes about the code". It is what the board draws, because a
board is a flowchart of names read along one line and a full name is a sentence: the two are
the same "two views of one record" the board and `show` already are. Resolved exactly as
`name` is — a named step's `display` lives in its definition and an edit reaches every plan
naming it, an on-the-fly step's lives on the step.

REQUIRED, on every step, and so is a `deps` on every step but the plan's first — or, where
a start is deliberate, a `root: true` saying so; a plan
carries a `display` of its own too, longer, since it owns the board's whole header line and
is drawn there INSTEAD of the title. Required because optional is what was tried: not one
plan in the live store ever set either field, so every step landed in column zero with no
arrows and the board drew a column of half-sentences clipped at 22 columns. There is no
length cap and no per-cell clip any more — the cap is what cut the informative half — and
the enforcement is three doors rather than one: the shape verbs refuse, every other write
warns and still writes, and `show`, `list` and the board draw the defect. See `_faults`.

A definition may also carry a `command`: the one standard shell command that step is run
with, `<PR>`- and `<PLAN>`-style placeholders and all, resolved onto a named step exactly as
`name` and `display` are. It is DATA and nothing here runs it — the agent owning the step is
what runs a command, because a plugin that fired them would be the evaluator this design does
not have. It exists so that the command is under the step when the step is read rather than
somewhere the owner has to go and look for it, which is the whole saving; most definitions
have no single standard command and carry none.

A definition may COMPOSE — `{"steps": ["a", "b"]}` — and naming it puts a and b in the plan,
flat. What a plan holds is always flat: no step contains another, because a step that did
would be a plan by another name. Composition is the one edge in this file that is actually
traversed, which is why a cycle in it is REFUSED where a cycle in a plan's `deps` is not: a
`dep` nothing walks is a lead's mistake to read, and a composite that composes itself is a
hang. Expansion mints fresh ids from the plan's own counter, like every step in it.

A definition may also OBLIGE another — `merge` obliges `merge-human-review` — and naming it
adds both. The obliged step carries `obliged_by`, the id of the step that brought it, and it can
be skipped with a reason like any other. What it cannot be is omitted: the obligation is a
property of the definition rather than a rule an agent remembers, so there is no way to name
a merge step and end up without its review on the board. A skip is a state with a sentence
beside it and a bad call can be questioned; an omission is invisible, which is enforcement in
appearance only. An on-the-fly step called "merge the PR" obliges nothing, and that is not a
hole — it is a word-only step, and the obligation belongs to the definition, not to the word.

Every obliging step gets its OWN obliged step, and nothing is ever deduplicated: two merges
are two diffs and therefore two reviews, whether they arrive in one act or two. A dedupe
would let one step's obligation be satisfied by a step it has nothing to do with, which is
the door round the obligation in a tidier coat — and a lead who thinks one review covers
both skips the second with that as the reason, which is visible where a dedupe was not.
Composition may repeat a definition; obligation never merges one. What stops obligation
running forever is not a dedupe but a cycle check, the same one composition gets.

A definition that both composes and obliges is REFUSED when it is expanded. An obligation
attaches to a step, and a composite is not a step in a plan — only its parts ever appear —
so there is no step for `obliged_by` to name. Dropping the obligation instead, which is what
an earlier draft did, loses one silently, and losing one silently is the single thing this
mechanism exists to prevent. Refused at expansion rather than at the load, so that one
malformed definition takes down only the commands that actually reach it: a catalogue is
edited by hand, and a typo in it must not be able to make every plan in the repo unreadable.

AN OBLIGATION IS NOT AN ORDER, and a definition says where it runs in a field of its own:
`anchor`, one word on the fixed spine every landing change has (`_ANCHORS`). `create-pr`
obliges `change-approval` — no PR without an approved contract — and an approval runs at the
very start, so reading the order off the obligation put it in the one place it cannot be.
The anchor is what `_place` reads to write a new step's deps, so a change approval named
into a plan of work lands as an early root and a review lands after the work, whatever order
they were named in. A definition with no anchor keeps the placement this file always gave
one: after whatever the plan currently ends with.

Templates are `templates/*.json`: preconfigured plans, COPIED on use and never linked back.
`template list` browses them, because nobody knows at the start of a job that a template
exists for it — the lead looks once the work is shaped. A copy holds no reference to what it
came from and deleting the template file changes nothing about it. What a copy does carry is
the links: a named step inside a template stays a name, so it is still resolved live. Copies
and links are the two halves of this design and they point opposite ways on purpose.

Templates hold no `deps`. A template entry may expand into several steps, so an edge written
against an entry would have nothing single to attach to; edges are written into the copy's
own file once it exists. Every OTHER key on an entry is a field on the step it mints, copied onto it
blind (`_written`) — a gate, an owner, a checkpoint, a skip and its reason have no verb,
so a template that could carry only a name could not show what a step really looks like.

The catalogue is deliberately nearly empty — `change-approval`, `create-pr`, `merge`,
`merge-human-review`, `review` and one template — because the design says what to promote
into it is read off real runs rather than decided up front, and the system has to work
with it almost bare. It does: with no `library` directory at all every verb here still
works and only `name-step` has nothing to offer.

Plan ids are `p-<n>`, monotonic across the store and never reused. STEP IDS ARE PER PLAN:
every plan numbers its own from `step-1`, out of a `next_step` counter in its own file, so
two plans are completely independent and nothing one does moves the other's numbers. Both
counters are stored and recomputed as floors on read — over the ids on disk for `next_plan`
and over that plan's own steps for its `next_step` — so a hand-deleted row cannot make the
next mint hand out an id somebody already wrote down.

What globality bought was a step id that named a plan by itself, and that is bought instead
by addressing: `p-16/step-3` always works, and a bare `step-3` resolves when exactly one
plan holds it and otherwise refuses naming the candidates (`_locate`). Almost every worktree
holds one plan, so the bare form is what is typed and the qualifier is what is available.

Nothing is renumbered. Plans made before this keep their `s-<n>` ids — a changelog quotes
ids as free text and rewriting one is the thing the guide forbids — and both spellings, plus
a bare number, resolve. `_meta.json`'s `next_step` is vestigial: it is kept written for a
store still on format 1 and for an older plugin on the same repo, and nothing here mints
from it.

A plan is keyed on the WORKSPACE NAME — the string `agents.workspace` and `workspaces.name`
hold, which is what the board groups by and what a later PR reads to decide a plan's
worktree is gone. It is resolved ONCE, at `create`, and stored; no verb recomputes it and
none re-attaches a plan to another key. A plugin `Context` has no store handle by design, so
the resolution is a shell-out to sb itself (`inspect` for an agent caller, `workspace list`
to map this checkout's path otherwise) — D2's sanctioned path, and the only one that returns
the same string the board uses.

The branch is NOT that name, which an earlier draft of this file had wrong. A branch changes
under a checkout that stays what it was: `git checkout -b fixups` in a worktree made a plan's
key drift away from the worktree it belongs to, and `list` went blind to it with nothing
recording that it had. The checkout PATH is what does not move, so it is stored beside the
name and is what "on this worktree" matches on — no subprocess on the read path, and a plan
found from the directory it belongs to even after a rename.

A checkout that is no workspace sb knows has no name to store, and that is written down as
`null` and rendered as itself rather than filed under a plausible-looking wrong key. A plan
under a key no workspace has would read, to the PR that derives records, as a worktree that
is gone — abandoned rather than live.

`workspace_from` says HOW that was decided — `agent`, `workspace-list`, `none`,
`unavailable` — because a null on its own is two different facts wearing one face. `none`
is sb answering that this checkout belongs to no workspace; `unavailable` is sb not
answering at all, which is a hiccup at one instant and not a statement about the job.
Nothing recomputes the field, so a plan made during a hiccup would otherwise carry a
worktree-is-gone verdict for the rest of its life.

Nothing about liveness is stored: whether the workspace still exists, whether anybody is
working in it, and whether a step's owner is alive are all read at display time and never
copied in here. Two records both claiming to know who is working will disagree.

What is read and never written
------------------------------

`show` and `list` render two things this file does not hold. `_Live` is where both are
asked, once per command, sharing one `_Budget` with the resolver above.

A step's OWNER STATUS — working, idle, blocked, done, dead — comes off `sb status --json`
at the moment the step is drawn, and is put on a COPY of the step (`_viewed`), never on the
step. That is the design's "the lead learns of a death by reading the plan, not by being
told": switchboard's failure notice goes to the dead agent's parent, which may be neither
the lead nor the step's owner's owner, so nothing has to be routed anywhere — the lead
looks, and the death is on the line. `sb status` rather than `sb inspect` per owner because
one question answers for every step of every plan being rendered, where inspect is one
subprocess each and is refused across the tree boundary anyway.

A plan's CONDITION — live, dormant, finished, abandoned — is derived the same way and for
the same reason: there are no lifecycle hooks, nothing tells this plugin that an agent was
closed or a worktree deleted, and the sweep that deletes one runs with nothing of the
plugin's alive. A stored condition would be wrong from the first sweep onwards.

Both are FAIL-SAFE IN ONE DIRECTION, which is most of the care in `_Live`. An sb that does
not answer produces `unknown` — never `dead`, and never `abandoned`. The direction matters
because these words are read cold by the analysis pass: a healthy job that read as
abandoned for one instant leaves the same mark as one that really fell apart.

"Its worktree is gone" is decided from the CHECKOUT PATH and from nothing else. It is not
decided from `workspace: null`, which is the trap this was written to avoid: `_workspace`
stores that null both for a checkout that is no workspace (`none`) and for an sb that could
not be asked (`unavailable`), and reading the second as a worktree that has gone would let
one timeout, at one instant, mark a live job abandoned for the rest of its life. A path
that is not there is evidence needing nobody's cooperation; a path that cannot be checked
is `unknown`, and `unknown` is never `gone`.

Everything a row is drawn from is escaped on the way out (`_flat`), and every verb refuses
a control character in the text it is handed. A row on a board is a LINE, so a step called
"write it\\ns-9  done  merged" would otherwise draw a step nobody added — and the same
newline in an owner draws a status nobody read. Refusing at the door is the good error
message; escaping at the render is what also covers a hand-edited plan file, a name in
the library and the refusals themselves, none of which came through a verb. An id is the
sharpest of those: a refusal is what HAPPENS when an id fails to validate, so the message
is built out of the one value nothing has vetted.

The set is a property and not a list. What must not survive is anything `str.splitlines()`
will break a line on — which is C0 and the C1 range, and also U+2028 and U+2029, which no
"control character" range catches and which a test sweeps the whole codespace to pin.

The changelog
-------------

Written by the command, carrying the reason the agent supplied. That is the record of how a
job actually ran where a command ran it: a plan gets reshaped as it goes, and without this
the file keeps only the final shape.

NOTHING VALIDATES IT AND NOTHING REFUSES ON IT, which is a decision and not a gap. `_write`
used to reject a document whose changelog had shrunk or whose entries had moved, and the
guide used to require a hand-edit to append its own entry in the shape of the ones already
there. Both were built for a plan a human maintained in an editor. What a plan is edited by
now is an agent with ordinary file tools, and rewriting the file whole is the normal way to
change one — so the check stood in the way of the interface it was meant to protect, and
the requirement made every edit pay for a record nothing surfaced. The verbs still stamp
their own entries (`_log`), so the story a command can tell is still told; what is gone is
an obligation on the hand that edits the file. What `_write` still refuses is a write that
drops a PLAN, which is the loss that cannot be reconstructed from anything.

Storage is one file per plan, each rewritten whole via tmp + `os.replace`, and NO coarse
lock — see `LOCK` above and `_minting`. `os.replace` is atomic within a directory, so a
reader sees one version of a plan or the other and never half of one; two commands touching
two different plans were never in each other's way; and the one thing per-file storage does
not answer by itself — two `create`s minting one id — is what the short mint lock is for.
Two writers on ONE plan is a convention rather than a mechanism, because a hand-edit in an
editor takes no lock and never could.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import textwrap
import time
from pathlib import Path
from typing import Any, Optional

from switchboard.plugins import Result

API = 1
VERSION = "1.0.0"
SCOPE = "repo"

# NO COARSE LOCK. sb offers one — an exclusive flock around the whole handler — and this
# plugin used to take it for every command, including the reads. One plan is one file now,
# and the shape is what makes the lock unnecessary rather than a preference: a write is
# tmp + `os.replace`, which is atomic within a directory, so a reader sees one version of a
# file or the other and never half of one, and two commands touching two different plans
# were never in each other's way to begin with.
#
# What is left is `_minting` — a short lock the four verbs that ALLOCATE AN ID take, and
# nothing else does. Ids come from counters shared by the whole store, so that one is a
# real race and is the only one this file can fix. What it cannot fix, and does not
# pretend to: two writers on the SAME plan, where the second read the file before the
# first wrote it and its write is the one that survives. That is the design's "one writer
# per plan — the worktree's owner" convention, stated in `guide`, and no lock this file
# takes would make a hand-edit in an editor participate in it anyway.
LOCK = False

# TWO SHAPES, and the store is in whichever one is on the disk. `FILE` is the original:
# every plan in one `plans.json`, format 1, which is what an older plugin reads and writes.
# After `migrate`, one plan is one `p-<n>.json` flat in the state dir, beside a small
# `_meta.json` holding the counters and the format marker, with a format-2 tombstone left
# at `FILE` so an older plugin refuses the store instead of writing a second one beside it.
#
# The store is shared by every worktree in a repo and the worktrees update one at a time,
# which is why nothing here flips the shape on its own: a plugin that migrated the first
# time it read would take down every worktree still on the old code. `format` is this
# plugin's own; sb neither reads it nor has an opinion about it.
FILE = "plans.json"
MIGRATED = "plans.json.migrated"
META = "_meta.json"
FORMAT = 2
LEGACY_FORMAT = 1

# What `create`, `tick` and `skip` write into a step's `progress`. Not an enum — see the
# module docstring. These three are what this plugin's own verbs write; a lead that types
# `progress: waiting on Andrew` into the file by some later verb is not violating anything,
# which is why nothing below compares against this list to decide whether a move is allowed.
OPEN, DONE, SKIPPED = "open", "done", "skipped"

# How a plan's workspace was decided, stored as `workspace_from`. Four values and no more,
# because this one IS a closed vocabulary: it describes what this code did, not what a job
# is like, and the PR that derives records has to be able to switch on it. The two that
# matter are the two that both leave `workspace` null — see `_workspace`.
BY_AGENT, BY_LIST, NONE, UNAVAILABLE = "agent", "workspace-list", "none", "unavailable"

# What a plan READS as when it is displayed. Derived every time and stored never — see the
# module docstring for why there is no other honest option. `UNSURE` is not a failure: it
# is the answer whenever the evidence for one of the other four could not be got, and it is
# what stands between a wedged sb and a plan that reads as abandoned.
LIVE, DORMANT, FINISHED, ABANDONED, UNSURE = (
    "live", "dormant", "finished", "abandoned", "unknown")

# Where a plan's worktree is, as far as anything can be confirmed at this instant. Three
# values and not two, for exactly the same reason.
HERE, GONE = "here", "gone"

# A step's owner as the agent reads right now. The rest of the vocabulary is the store's
# own (`working`, `idle`, `blocked`, `done`), passed through rather than re-spelled here.
# `DEAD` is something sb reported; `UNSEEN` is sb not saying, and the two must never be
# confused — which is why an owner missing from a snapshot that DID arrive is still unseen.
DEAD, UNSEEN = "dead", "unknown"

# The states an agent row never moves out of: the store's word for a closed agent. Every
# agent on a worktree in one of these is what "dormant" means.
CLOSED = ("done", "failed")

# The catalogue, shipped beside this file rather than kept in per-repo state: definitions
# and templates are what the plugin KNOWS, not what a repo has done, and a repo that wants
# its own puts a whole `plans` plugin under `.switchboard/plugins/` — which replaces this one
# wholesale, folders and all. Nothing here writes into either directory; a definition is
# edited in an editor, which is also what makes "editing one reaches live plans" true with no
# verb to implement it.
LIBRARY, TEMPLATES = "library", "templates"

# WHERE A NAMED STEP RUNS, as a point on the one spine every landing change has. A
# definition's `anchor` is one of these words and nothing else, and the order of this tuple
# IS the order of the work: design before build, build before review, review before the PR,
# the PR before the human's pass, and the merge last.
#
# It exists because ORDER AND OBLIGATION ARE DIFFERENT FACTS and this file used to derive
# the first from the second. `create-pr` obliges `change-approval` — no PR without an
# approved contract behind it — and the obligation edge put the approval immediately before
# the PR, which is the one place in a job it must never be: an approval is the gate before
# any code, so it landed mid-chain and the lead re-deped it to the front of the plan every
# single time. The obligation was right and the edge was wrong, because "you may not do X
# without Y" says nothing whatever about when Y runs.
#
# So obligation keeps its own job — materialising the step, never optional, never deduped —
# and the anchor says where each of them goes. `_place` is what reads it: a step lands after
# the sinks of the NEAREST LOWER BAND that is actually in the plan, so a review named into a
# plan of implementation steps waits on the implementation, and one named into a plan that
# has none waits on whatever is earlier than it that IS there. A step with nothing earlier
# than it in the plan is a deliberate root and says so — which is exactly what a change
# approval is, whatever order it was added in.
#
# AN ANCHOR LOOKS BACKWARDS AND NEVER FORWARDS. A step is placed against the plan as it
# stands and nothing already in the plan is re-deped, because a command changes the steps it
# names and rewriting a lead's edges behind its back is a worse fault than the one being
# fixed. `create --lib` sorts what it was given, so one call is order-insensitive; steps
# named one at a time in the reverse of the order they run land in the order they were
# named. Said in `guide` and in `_place`, because it is the one thing about this field an
# agent can get wrong without being told.
#
# A CLOSED VOCABULARY, unlike `progress` and `gate`, and for the reason those are open: the
# whole meaning of an anchor is its position in this order, so a word not in it has no
# position and there is nothing honest to do with it but refuse. A definition with no anchor
# at all is a different thing and is fine — it is an ordinary piece of the work, ranked with
# `build`, and it keeps the placement it had before anchors existed (after whatever the plan
# currently ends with). That is what makes a repo's own library, written against the older
# shape, go on working unchanged.
_ANCHORS = ("design", "build", "review", "pr", "pre-merge", "merge")
_UNANCHORED = _ANCHORS.index("build")

# `p-1`, `P-1`, `plan-1` and a bare `1` all name the same plan; likewise `s-1`, `step-1` and
# `1` for a step. An id is read out of a board or a spawn prompt and retyped, and being
# strict buys nothing. The long forms are what the markdown dump renders (see `_markdown`),
# so a reader who copies `plan-1` out of a pull request comment can type it straight back —
# nothing MINTS a `p-`, and nothing mints a `step-` for a plan made before per-plan
# numbering, which is exactly why both spellings have to resolve.
_PLAN_ID = re.compile(r"^(?:p(?:lan)?-)?(\d+)$", re.IGNORECASE)
_STEP_ID = re.compile(r"^(?:s(?:tep)?-)?(\d+)$", re.IGNORECASE)

# Long enough for a real sentence, short enough that a plan stays readable when it is shown.
# Anything longer wants a brief, and briefs are files a checkpoint can point at.
MAX_TEXT = 500

# Everything that is not text on a line: the C0 range including newline, tab and escape,
# DEL, the C1 range a terminal may still act on, and U+2028/U+2029. A row is a line and a
# field is part of one, so any of these in a stored field is either a paste or an attempt
# to draw a row nobody added. Refused by every verb and escaped by every renderer.
#
# The two Unicode separators at the end are the ones a C0/C1 range misses, and they are the
# reason the property this class has to hold is stated as a PROPERTY and pinned by a test
# that sweeps `str.splitlines()` over the whole codespace rather than by a second hand-
# written list: what matters is not that these look like control characters but that
# nothing Python will break a line on can survive. U+2028 draws as a box or as nothing in a
# terminal, so a human reading `show` was never the target — the target is any consumer
# that splits the rendering into rows, which is what a board does.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
_ESCAPED = {"\n": "\\n", "\r": "\\r", "\t": "\\t", "\x1b": "\\e",
            "\u2028": "\\u2028", "\u2029": "\\u2029"}


def register(reg):
    reg.command(
        "guide", guide, audience="both",
        help="how plan-making is done — when a plan exists, who writes to it, what to "
             "build it from, and how to edit one")
    reg.command(
        "create", create, audience="both",
        help="start a plan on this worktree, empty or with its steps already in it",
        args=[reg.arg("title", repeat=True, help="what this plan is for"),
              reg.arg("--display", help="the plan's board name — a display version of the "
                                        "title, one line, required"),
              reg.arg("--step", repeat=True,
                      help="a step, as `<board name> = <what it is>`; repeat for more, "
                           "and they are chained in the order given"),
              reg.arg("--lib", repeat=True,
                      help="a library step by name, e.g. review; repeat for more, and "
                           "each lands where its definition says it runs"),
              reg.arg("--note", repeat=True, help="a note on the plan; repeat for more"),
              reg.arg("--reason", help="why, for the changelog")])
    reg.command(
        "list", ls, audience="both", help="the plans on this worktree",
        args=[reg.arg("--all", flag=True, help="every plan, on every workspace")])
    reg.command(
        "show", show, audience="both",
        help="one plan in full — steps, deps, changelog; or one STEP in full, with the "
             "instructions for doing it",
        args=[reg.arg("id", help="a plan id (p-1), or a step id (step-2, p-1/step-2) for "
                                 "that one step and how it is done"),
              reg.arg("--markdown", flag=True,
                      help="render that one plan as markdown, for posting where a human "
                           "reads it — a PR comment. Walked, not templated: it survives "
                           "the schema changing")])
    reg.command(
        "changelog", changelog, audience="both", help="what has been done to one plan",
        args=[reg.arg("id", help="a plan id, e.g. p-1")])
    reg.command(
        "validate", validate, audience="both",
        help="check a plan after editing it by hand — what will not load, and what is "
             "incomplete; it reports and refuses nothing",
        args=[reg.arg("id", repeat=True,
                      help="a plan id, e.g. p-1; omit for every plan in the repo")])
    reg.command(
        "tick", tick, audience="both",
        help="mark a step done — nothing infers progress and nothing else writes it",
        args=[reg.arg("step", help="a step id, e.g. step-1, or p-2/step-1 to say "
                                   "which plan"),
              reg.arg("--reason", help="why, for the changelog")])
    reg.command(
        "note", note, audience="both", help="append a note to a step, or to a plan",
        args=[reg.arg("target", help="a step id (step-1, or p-2/step-1) or a plan id "
                                     "(p-1)"),
              reg.arg("--text", help="the note"),
              reg.arg("--reason", help="why, for the changelog")])
    reg.command(
        "skip", skip, audience="both",
        help="mark a step skipped, with the reason — a skip is a state with a sentence "
             "beside it, never an absence",
        args=[reg.arg("step", help="a step id, e.g. step-1, or p-2/step-1 to say "
                                   "which plan"),
              reg.arg("--why", help="the reason, which renders beside the state and is "
                                    "required"),
              reg.arg("--reason", help="why, for the changelog; the skip's own reason is "
                                       "`--why` and is what shows on the step")])
    reg.command(
        "library", library, audience="both",
        help="browse the step definitions a plan can name, or read one in full",
        args=[reg.arg("name", repeat=True,
                      help="a definition to read; omit for all of them")])
    reg.command(
        "name-step", name_step, audience="both",
        help="add a step from the library — a link to its definition, never a copy",
        args=[reg.arg("plan", help="a plan id, e.g. p-1"),
              reg.arg("name", help="a library definition, e.g. merge"),
              reg.arg("--reason", help="why, for the changelog")])
    reg.command(
        "template", template, audience="both",
        help="browse the preconfigured plans, or start one — `list`, or `use <name>`",
        args=[reg.arg("action", choices=("list", "use"), help="list them, or use one"),
              reg.arg("name", repeat=True, help="which template, for `use`"),
              reg.arg("--title", help="a title for the copy; the template's is the default"),
              reg.arg("--display", help="the copy's board name; the template's is the "
                                        "default"),
              reg.arg("--reason", help="why, for the changelog")])
    reg.command(
        "migrate", migrate, audience="both",
        help="move this repo's store from one plans.json to one file per plan — ONCE, and "
             "only when every worktree is on this version of the plugin")


# -- the plan-making instruction -----------------------------------------------


# The whole of how a plan gets made, printed on demand and carried on no spawn.
#
# It lives here, in the plugin, rather than in a preset or in `protocol.md`, so that
# disabling or deleting the plugin takes the instruction away with the commands it names.
# An instruction that outlives the verbs it tells you to type is worse than no instruction.
#
# Split from the fragment on the design's own reasoning: the trigger is paid on every spawn
# forever and the instruction is read once, when a job comes up. Merging them would put
# this text in every system prompt in the fleet to be read by the agents it does not apply
# to; leaving the trigger out would leave this text unreachable, because nobody looks up an
# instruction they were never told exists.
#
# It states the condition, the owner and the route, and stops. It does NOT state what any
# named step involves, what happens at a gate, or what any verb does. Every one of those
# has a home that is read at the moment it applies — a definition's own `about` for a step,
# `sb presets` for a format, `sb plugin plans` for the verbs — and a second copy here would
# be a copy going stale against the thing it describes. This text is a pointer to those
# homes plus the few rules that have nowhere else to live.
#
# So what stays is what is true about EVERY plan and about no particular step: when one
# exists, who is allowed to write to it, what to build it out of, and how to edit the file
# without losing the record. Gates used to be here at length and are not any more, not even
# named: a gate is a property of the step whose exit condition it is, so the step that
# carries one is where an agent that has reached it will look, and naming them here just
# put a second, staler account in front of every agent that had not.
GUIDE = """\
Plan-making — read this when a job comes up, not before.

WHEN A PLAN EXISTS

  A plan exists exactly when the work is heading for a change that will land. Small is not
  exempt: a one-line docs change bound for a PR gets a plan, only a short one.

  Everything else runs without one — investigation, questions, scouting, review-only work,
  anything a single agent answers and reports, and everything a dispatcher does.
  Investigation PRODUCES a plan rather than living inside one; it is a step only when it is
  one piece of an already-shaped job.

WHO WRITES TO IT

  The worktree's owner: the lead, or the sole worker where there is no lead. A sole worker
  counts as a lead for this and nothing else — planning the work you were given is how the
  task is carried, not work you took on.

  The owner makes every edit to the SHAPE of the plan — steps, order, owners, gates, deps.
  A child that wants one ASKS, with `sb tell parent`, and does not edit the file. One
  writer is what makes editing this file by hand safe, and it is the only thing that does.

  TICKING IS NOT THAT. Any agent ticks the step it did, and is trusted to tick only that
  one. An agent that reports back without ticking leaves the tick to the lead, who does it
  on the report — or, if the step is not actually done, does something else about it.

  A dispatcher is never involved in a plan. It relays work and makes agents and worktrees;
  it does not plan, own, tick or read one.

WHAT TO BUILD IT FROM

  Look before inventing — you are not expected to know what already exists:

      sb plugin plans library                the named steps, and what each one is
      sb plugin plans template list          the preconfigured plans
      sb plugin plans template use <name>    start from one
      sb plugin plans create "<what for>" --display "<board name>" --step "<short> = <what it is>"

  ONE COMMAND MAKES THE WHOLE PLAN. `--step` invents a step and `--lib <name>` names one
  out of the library, in the same `create`; repeat either as often as you like:

      sb plugin plans create "make X work" --display "make X work end to end" \\
          --step "impl = write it" --step "tests = pin it" \\
          --lib create-pr --lib merge

  That is a whole shipping plan, and it lands with its edges right. The `--step`s chain in
  the order you typed them. A `--lib` step lands where its definition says it RUNS rather
  than where you typed it, so the order of those flags decides nothing.

  IN ONE `create` IF YOU CAN, because that is the call that sorts them. A step added later
  — `name-step`, or written into the file — is placed against the plan AS IT THEN STANDS,
  and nothing already in the plan is ever re-deped: `name-step merge` before `name-step
  create-pr` leaves the merge waiting on the implementation, because that is what the plan
  ended with when it was named. Name them in the order they run, or fix the edge in the
  file afterwards, which is one field.

  NAME THE OUTERMOST STEP AND WHAT IT OBLIGES ARRIVES WITH IT — the two flags above land
  seven steps, because `create-pr` obliges the change approval, which obliges the review,
  and `merge` obliges the human-review list. Naming those as well gets you a SECOND copy of
  each: nothing is ever deduplicated, since two merges are two diffs and therefore two
  reviews. Read `library` first and name the ones nothing else brings.

  A definition carries its own account of how that step is run — what it obliges, what it
  gates, what finishing it means. Read it there. Nothing about any particular step is
  repeated here, so that nothing here can be out of date about one.

  Then re-plan on what you now know, rather than executing a split you decided before you
  knew anything.

EVERY STEP HAS A BOARD NAME AND A DEP

  Both are required, and both exist for the same picture: the board draws a plan as a
  left-to-right flowchart of its steps, and it draws that out of the deps and labels the
  file holds. Without them a plan is a column of half-sentences with no arrows, which is
  what every plan looked like before this was required.

    - A BOARD NAME on every step, written with the name in one flag so the two cannot come
      apart: `--step "list claims = list every claim the document makes"`. A step added to
      a running plan is written into the file with a `display` of its own, the same way.
      Make it as short as it can be and still READ as words — abbreviate, and cut what the plan's own title already
      says, which is on the line above it. `list every claim the document makes` is `list
      claims`; `human review` is `review`. No length cap and nothing clips it, and no
      vowel-stripping either: a label nobody can pronounce is not a label.

    - A BOARD NAME ON THE PLAN too, and this one is LONGER — it owns the board's whole
      header line, so it is a display version of the title rather than an abbreviation of
      it: `create "fix the red CI on main, which has been failing since Tuesday"
      --display "fix red CI: rich assertions on main"`. The board draws this INSTEAD of
      the title, and `show` is where the title is read.

    - A DEP on every step but the first: `"deps": ["step-1"]` on the step, which is what
      the arrows are drawn from. `create --step … --step …` chains what you typed in the
      order you typed it and `--lib` places its steps for you, so reshape from there
      rather than starting from nothing. A plan that genuinely has TWO STARTS says so —
      `"root": true` on the step — and then it is complete and draws green like anything
      else. Say it rather than inventing an edge to clear the warning: an order that never
      happened is a lie in the record, and the mark is what tells a deliberate start from
      a forgotten edge.

  WHAT HAPPENS WHEN ONE IS MISSING, because it is not the same everywhere. `create`,
  `name-step` and `template use` REFUSE to make a step with no board name.
  Every other verb — `tick` included — writes what you asked and then says what is
  incomplete underneath: a tick that would not land because of a rendering rule is worse
  than the rendering. `show` and `list` say the same thing, and the board draws the plan
  and the steps at fault in red. So a file edited by hand is never refused and never
  quietly wrong either.

EDITING IT — THIS IS THE NORMAL WAY, NOT THE FALLBACK

  The plan is a JSON file and editing it IS the interface. There is no verb for most of
  what a lead does to a plan — an owner, a gate, a checkpoint, a new step, an edge, a
  reworked step — because each of them was one field, and a verb per field is a surface
  nobody can hold in their head to do something a file edit does better. The shape of the
  job is:

      sb plugin plans create … / template use …    makes it, and prints the file
      read that file, then edit or write it        shape it: steps, owners, gates, deps
      sb plugin plans validate <plan>              ask what you broke

  READ IT AND EDIT IT WITH YOUR NORMAL FILE TOOLS. It is a JSON file on this disk like any
  other file you work on: read it, then edit or rewrite it. There is no editor to open and
  nothing to script — a read-modify-write through a one-liner shell interpreter is the
  slow way round something that is already a file.

  `create` and `template use` print the path of the file they just wrote, so there is
  nothing to derive. If you have lost it, the plans live here:

      $(git rev-parse --git-common-dir)/agentflow/plugins/plans/

  One plan is one `p-<id>.json` in that directory. On a repo whose store has not been
  moved across yet, every plan is instead in a single `plans.json` there — list the
  directory and you can see which you have. (`sb plugin plans migrate` moves a repo to one
  file per plan, once, and its own output says what that costs.)

  THE FILE ITSELF IS THE SHAPE TO WRITE AGAINST, and it is the only shape. `sb plugin
  plans show <plan> --json` is a VIEW of that plan and not a copy of it: the library is
  resolved into it, so what it prints for a `def` step — its `name`, its `display`, its
  `command` and its `anchor` — is not what the step holds and must never be written back
  into the file. A `def` step's own record does not carry any of the four, which is what
  makes the link live: the definition owns them and an edit to it reaches every plan.
  Two rules:

    - NEVER drop or rewrite a changelog entry that is already there, or a plan. Records
      are kept and never erased; cleanup means dropping out of the UI. You do not have to
      ADD an entry for a hand-edit — the verbs stamp their own and nothing here validates
      or refuses on the strength of that record.
    - ADD A LIBRARY STEP with `create --lib` or `name-step`, not by hand. It pulls in what
      the definition composes and obliges — and what those oblige in turn, so one name may
      land several steps at once, placed where each of them runs. A `def` you type by hand
      resolves its label, its name and its `command` like any other named step, and it is
      a perfectly good thing to write; what it does NOT do is materialise the steps its
      definition obliges, which is the whole reason the obligation is not a memory.

  WHICH FIELDS ARE YOURS TO WRITE. Everything a verb mints is in the file already; these
  are the ones that only ever arrive by editing it, and each says who writes it and when.
  `sb plugin plans template use docs` is one worked example of every one of them.

    owner        the plan's owner, as it hands the step out. A name, and nothing is told:
                 the plan never pushes to a running agent, so say so yourself.
    gate         the plan's owner, as it shapes the plan. The sentence a human has to
                 answer before this step is finished — a FIELD on the step whose exit
                 condition it is, never a step of its own. No verb clears it: the owning
                 agent blocks, and the human answering that agent clears both.
    progress     `open` at mint, `tick` writes `done` and `skip` writes `skipped`. An open
                 vocabulary, so `waiting on Andrew` is a progress too if that is what is
                 true — write that one by hand, with its reason in `why`.
    why          the reason for whatever `progress` currently says — `skip --why` writes
                 it, and a hand-written progress needs it written in the same edit. A skip
                 with no reason is drawn red. Overwritten by whatever moves the step next,
                 so it is never a history.
    tries        bumped by whoever re-enters the step, with `progress` put back to `open`.
                 Leave a `note` saying what the second run was for; a count that went up
                 with nothing behind it is a record nobody can account for.
    checkpoints  references — a path, a URL, an id — added by whoever produced the thing:
                 `[{"ref": "notes/the-brief.md"}]`. Never content. A ref with a line break
                 in it is somebody pasting a brief instead of pointing at one.
    output       the step's own finished content, written by the AGENT THAT DID THE STEP
                 as it ticks. The one field here that is content rather than a reference,
                 because `create-pr` dumps it onto the pull request and a reference does
                 not dump: an approved change contract and a review's result are what it
                 is for, and the definitions needing one say so in their own `about`.
                 Multi-line; replaced and never appended when a step is redone.
    display      required on every step, and `deps` on every step but the first — see
                 above. The minting verbs refuse a step without a board name.

  `id`, `def`, `name`, `obliged_by` and the plan's `next_step` are MINTED and are not
  yours: a `def` typed by hand brings neither what its definition composes nor what it
  obliges, and `next_step` is the plan's own step counter, which shows up as a row in the
  `--markdown` dump because that rendering reads the record rather than a schema. A
  definition's `command` is not on the record at all — it is resolved out of the library
  every time the step is drawn.

  A FIELD THIS LIST HAS NEVER HEARD OF IS ALLOWED. There is no schema to satisfy: put what
  the job needs on the step, and `show`, `--json` and the PR comment all print it — a
  scalar gets its own line under the step in the terminal, and anything with a shape to it
  is left to `--json`, which is the rendering that can carry one.

  Three verbs are worth typing rather than editing, being frequent, small and usable by
  the agent that did the work rather than only by the plan's owner — `tick <step>` when a
  step is done, `skip <step> --why "<reason>"` when it is not going to be, and `note
  <step> --text` for what happened. A `tick` or a `skip` also prints what it just
  unblocked, in full, so the next step's own instructions arrive as you reach it. `sb
  plugin plans show <step>` is that same view of one step asked for on purpose — the step,
  its command, and how its definition says it is done. `sb plugin plans --help` lists the
  rest.

  HOW A STEP IS ADDRESSED, since every one of those takes one. Each plan numbers its own
  steps from `step-1`, so `step-3` on its own resolves while exactly one plan holds that
  number — which is the usual case, a worktree holding one plan — and otherwise refuses,
  naming the plans it could have meant. `p-16/step-3` names the plan on the front and
  always works, and is what that refusal is asking you for. A plan made before per-plan
  numbering keeps its `s-<n>` ids and nothing is renumbered; both spellings, and a bare
  number, resolve.

  WHAT VALIDATE IS FOR. Nothing watches the file, so an edit is noticed when something
  next reads the store — the next command, or the board, which redraws every few seconds
  and paints a plan and the steps at fault in red. `validate` is that same check asked for
  on purpose, at the moment you finish an edit: it names what will not load and what is
  incomplete, on one plan or on all of them, and it refuses nothing whatever it finds.

  TICK A STEP BEFORE ITS TEARDOWN RUNS, never after. A step that closes the last agent or
  deletes the worktree takes with it whatever was going to tick it, so a tick that waits
  for the command to finish is a tick that does not happen.
"""


# -- the handlers --------------------------------------------------------------


def guide(ctx, args) -> Result:
    """Print the plan-making instruction. Reads nothing and writes nothing.

    A verb rather than a preset because a preset survives the plugin being deleted, and
    this text is a list of commands that would then not dispatch. `data` carries the same
    string so a machine reader gets the instruction rather than a rendering of it.
    """
    return Result(human=GUIDE.rstrip("\n"), data={"guide": GUIDE})


def create(ctx, args) -> Result:
    """A plan on this worktree, with as many of its steps as are known already.

    Both halves matter: a plan may be defined upfront, which the design says is the point
    rather than overhead, and a lead that has not shaped the work yet still gets somewhere
    to put it. Neither is the special case.

    A BOARD NAME ON THE PLAN AND ON EVERY STEP, and the step's is written in the same flag
    as its name — `--step "list claims = list every claim the document makes"`. One flag
    because `--step` repeats: a parallel `--display` list pairs by position, so a list one
    short pairs every step after the gap with the wrong label, silently, in a field nobody
    re-reads. The steps are then chained in the order they were given (see below).

    `--lib` NAMES A LIBRARY STEP IN THE SAME CALL, which is the difference between a plan
    landing in one command and landing in one plus an unbounded number of follow-ups. It
    is the same expansion `name-step` does — what the definition composes, what those
    oblige — and the steps it lands are placed by their ANCHOR (`_anchor`), so where a
    `--lib` sits among the flags does not decide where it sits in the plan. That is the
    one thing about this flag not to mistake for an omission: `--step` order IS an order
    and is chained, and a library step's order is a property of the definition instead.

    What `--lib` deliberately cannot seed is an owner, a gate or a non-linear dep, all of
    which name ids that do not exist until this command has minted them. Those stay
    edits to the file, which is now the cheap half of making a plan rather than the
    expensive one.
    """
    title = " ".join(str(w) for w in (args.title or ())).strip()
    display = str(args.display or "").strip()
    given = [str(s).strip() for s in (args.step or ()) if str(s).strip()]
    named = [str(s).strip() for s in (getattr(args, "lib", None) or ()) if str(s).strip()]
    notes = [str(n).strip() for n in (args.note or ()) if str(n).strip()]
    # The reason is in here with the rest: it is the field every later verb carries into
    # the changelog, and the cap is about a record staying readable when it is shown.
    bad = _cap(title, display, *given, *named, *notes, args.reason)
    if bad:
        return bad
    if not display:
        return _no_display(
            "a plan", "It owns the board's whole header line, so it is longer than a "
            "step's and is a display version of the title rather than an abbreviation: "
            "`--display \"fix red CI: rich assertions on main\"`.")
    steps = []
    for raw in given:
        short, name = _authored(raw)
        if not short or not name:
            return _no_display(
                "every step", "Write it in front of the name, in the one flag, so the two "
                "cannot come apart: `--step \"list claims = list every claim the "
                "document makes\"`.")
        steps.append((short, name))

    # The catalogue BEFORE the lock and before the write, for `_lib`'s reason: a verb that
    # wrote and then met a broken definition would report a failure over a plan that had
    # already landed. Read only when a `--lib` was actually asked for, so a typo in a
    # shipped JSON file cannot stop a plan being made that never names one.
    lib: dict = {}
    if named:
        lib, bad = _lib()
        if bad:
            return bad
        for want in named:
            if want not in lib:
                return _no_def(lib, want)
            if not str((lib.get(want) or {}).get("display") or "").strip():
                return _no_display(f"the '{_flat(want)}' definition",
                                   f"A named step draws its definition's label, so add a "
                                   f"`display` to `library/{_flat(want)}.json`.")

    # THE ONE LOCK LEFT, and it is held over this and nothing else: minting. See
    # `_minting` for why the other verbs need none and what is left unguarded.
    with _minting(ctx.state_dir):
        doc, seal = _read(ctx.state_dir)
        who = ctx.agent or "human"
        where, how = _workspace(ctx)
        plan = {"id": f"p-{doc['next_plan']}", "workspace": where, "workspace_from": how,
                "checkout": str(_here(ctx)), "title": title, "display": display,
                "next_step": 1, "steps": [], "changelog": [],
                "notes": [_note(n, who) for n in notes],
                "created_by": who, "created_at": int(time.time())}
        doc["next_plan"] += 1
        # CHAINED IN THE ORDER GIVEN, because the order they were typed in IS an order: a
        # lead writing `--step a --step b --step c` has just said what comes after what,
        # and the alternative — every step a root, every plan warning about itself the
        # moment it is made — makes the one-shot `create` unusable to be pedantic about
        # intent nobody doubts. A plan that is not a chain is reshaped in the file.
        for short, name in steps:
            step = _step(_mint_step(plan), name, display=short)
            if plan["steps"]:
                step["deps"] = [plan["steps"][-1]["id"]]
            plan["steps"].append(step)

        # THE LIBRARY STEPS LAST, and in ANCHOR ORDER rather than in the order the flags
        # were typed. The freetext chain above is the work itself, which is what a library
        # step is anchored against — a change approval before it, a review after it — so
        # placing these against a plan that already holds the chain is what makes one
        # `create` land the whole shape with its deps right. Each is minted separately,
        # against the plan as it now stands, exactly as a `name-step` would be.
        try:
            for want in sorted(named, key=lambda k: _anchor(lib, k)):
                plan["steps"].extend(_mint(plan, lib, want, after=tuple(_sinks(plan))))
        except _BadDef as e:
            return e.refusal()

        made = ", ".join(s["id"] for s in plan["steps"])
        detail = f"{_count(plan['steps'])} ({made})" if made else "empty"
        if how == UNAVAILABLE:
            # In the append-only record as well as in the field, because this is the one
            # thing about a plan that was never true of the job and cannot be re-derived
            # later: sb was not reachable at the moment this plan was made.
            detail += "; workspace unresolved — sb did not answer"
        _log(plan, who, "create", args.reason, detail)
        # The file, claimed with `O_EXCL` before it is filled: the second lock on the id,
        # and the only one that holds where `flock` does not. See `_reserve`.
        _reserve(ctx.state_dir, doc, plan)
        doc["plans"].append(plan)
        _write(ctx.state_dir, doc, seal)
    # `lib` is `{}` unless a `--lib` was given, and it was read on the way in either way:
    # a freetext plan holds no link to resolve, and a plan that does holds one whose
    # catalogue has already been opened, so nothing past the write can fail.
    return _plan_result(_shown(plan, lib), path=_path(ctx, plan))


def ls(ctx, args) -> Result:
    """This worktree's plans, because that is the only set anybody standing here is in.

    A plan belongs to one worktree and from inside it the others are invisible; `--all` is
    for a human looking across the repo, not for a lead deciding what to do next.

    Matched on the checkout PATH rather than on the workspace name, for two reasons that
    point the same way: the path is what does not move when a branch changes or a workspace
    is renamed, and matching on it costs no subprocess on a read that a board may run often.
    A plan with no `checkout` — one written by hand — is only ever shown by `--all`, which
    is the honest answer to "is this here?" when the record does not say.
    """
    doc = _read(ctx.state_dir)[0]
    plans, here = doc["plans"], _here(ctx)
    if not args.all:
        plans = [p for p in plans if _same(p.get("checkout"), here)]
    if not plans:
        return Result(human="\n".join(_broke(doc) + ["(no plans on this worktree)"
                                                     if not args.all
                                                     else "(no plans in this repo)"]),
                      data=[])
    # Resolved even though the list does not print step names: `data` is what PR4 and PR8
    # read, and a machine reader handed a step whose name is null has been handed a puzzle.
    # Only if some plan here holds a link, though — a repo whose plans never named one is
    # not a repo a typo in the catalogue gets to make unlistable.
    lib, bad = _lib(plans)
    if bad:
        return bad
    # One `_Live` for the whole listing, so twenty plans ask sb once between them and share
    # one budget. A board that renders this often must cost one bounded question, not one
    # per row.
    live = _Live(ctx)
    views = [_viewed(_shown(p, lib), live) for p in plans]
    return Result(human="\n".join(_broke(doc) + [_line(p, workspace=args.all)
                                                 for p in views]), data=views)


def _broke(doc: dict) -> str:
    """The plans that did not load, one line each, above the ones that did.

    One plan per file means a malformed one costs only itself — that is the point of the
    layout. But "costs only itself" and "is never mentioned" are different things, and the
    second is how a plan quietly stops existing: every verb would carry on, the board would
    draw the rest, and nobody would be told which file to go and fix. `data` is left alone,
    being the list of plans a machine reader asked for; this is the line for the terminal.
    """
    return [f"! {b['id']} did not load, and nothing here will overwrite it — {b['why']}"
            for b in doc.get("broken") or ()]


def show(ctx, args) -> Result:
    """One plan in full, with everything that is read rather than held read now.

    Two resolutions happen here and neither is written back. A named step becomes the words
    in the library, which is why an edit to a definition reaches a plan made last week; and
    every owner's status and the plan's own condition are read off sb at this instant,
    which is why a dead owner is on the line the moment a lead looks at it.

    A STEP ID SHOWS THAT ONE STEP, with the instructions for doing it under it. Same verb
    because it is the same question asked at a different scale — what is this — and because
    an agent that has been handed `step-4` should not have to learn a second command name to
    read it. `tick` and `skip` print this view unasked for what they release (`_next`); this
    is the way to ask for it, for a step nothing has just unblocked — the plan's own first
    step, or one being picked up again after a break.

    A SLASH SETTLES IT BEFORE THE PREFIX IS READ, exactly as `note`'s target does: `p-16/
    step-3` starts with a `p` and is a step, because the qualifier names the plan the step
    is in. A bare number is a PLAN here and not a step, which is the one place in this file
    that reads one that way and is the older meaning `show 1` has always had.
    """
    given = str(args.id or "").strip()
    if "/" in given or (given[:1].lower() == "s" and _num(_STEP_ID, given) is not None):
        return _one_step(ctx, given, markdown=bool(getattr(args, "markdown", False)))
    doc, _ = _read(ctx.state_dir)
    plan = _find(doc, args.id)
    if plan is None:
        return _missing(doc, args.id)
    # Resolved HERE and never in the file: this is the moment a link becomes text, which is
    # why an edit to a definition reaches a plan that was made last week and is running now.
    lib, bad = _lib([plan])
    if bad:
        return bad
    return _plan_result(_viewed(_shown(plan, lib), _Live(ctx)),
                        markdown=bool(getattr(args, "markdown", False)))


def _one_step(ctx, given: str, *, markdown: bool = False) -> Result:
    """One step, drawn as `show` draws a plan's rows — plus how it is done.

    The `about` is the whole reason this exists, and it is why the same text is NOT on
    every row of `show <plan>`: a definition's prose is a page, and a page under each of
    six steps is a plan nobody can see. Asked for one step at a time it is exactly the
    right length, because one step at a time is how it is worked.

    Read-only and resolved, like every other read here: the name, the label, the command
    and the instructions all come out of the library at this instant, and none of them is
    written back into the file.
    """
    doc, _ = _read(ctx.state_dir)
    plan, step = _locate(doc, given)
    if step is None:
        return _no_step(doc, given)
    lib, bad = _lib([plan])
    if bad:
        return bad
    shown = _resolve(step, lib)
    data = dict(shown, plan=plan["id"], about=_instructions(step, lib))
    if markdown:
        # The machinery out of the copy that is dumped and not out of `data`, exactly as
        # `_plan_result` does it — see `_MACHINERY`.
        return Result(human=_markdown({k: v for k, v in data.items()
                                       if k not in _MACHINERY}), data=data)
    lines = [f"{plan['id']}  {_flat(plan.get('title') or '(untitled)')}"]
    lines.extend(f"  {ln}" for ln in _step_lines([shown]))
    lines.extend(f"  {ln}" for ln in _how(step, lib))
    return Result(human="\n".join(lines), data=data)


def changelog(ctx, args) -> Result:
    """The changelog alone, for reading a finished job cold without the current shape."""
    doc, _ = _read(ctx.state_dir)
    plan = _find(doc, args.id)
    if plan is None:
        return _missing(doc, args.id)
    entries = plan.get("changelog") or []
    if not entries:
        return Result(human=f"({plan['id']} has no changelog — which should be impossible)",
                      data=entries)
    return Result(human="\n".join(_entry(e) for e in entries), data=entries)


def validate(ctx, args) -> Result:
    """Ask, on purpose, what is wrong with a plan — after editing the file by hand.

    Nothing new is checked here. Every one of these checks already runs: `_read` refuses a
    malformed file on any command that touches the store, `_defects` recomputes
    completeness after every write, and the board redraws both every few seconds. What
    this adds is a MOMENT to run them at — the one right after an editor was closed, with
    no board open and no other command to type — which is the whole difference between a
    rule that is enforced and a rule that is eventually noticed.

    It never refuses, whatever it finds, and that is not a technicality: this is the verb a
    lead types when it already suspects the file is wrong, so a non-zero exit would be the
    tool refusing to answer the question it was asked. A file that will not load is
    reported as the thing that is wrong with it, not raised.
    """
    wanted = [str(w).strip() for w in (args.id or ()) if str(w).strip()]
    try:
        doc, _ = _read(ctx.state_dir)
    except ValueError as e:
        # The store itself, not one plan: a legacy single file that will not parse, or a
        # counters sidecar from a newer plugin. Reported rather than raised — see above.
        return Result(human=f"! {e}", data={"ok": False, "store": str(e), "plans": []})

    lines = list(_broke(doc))
    found: list[dict] = []
    plans = doc["plans"]
    if wanted:
        picked = []
        for given in wanted:
            plan = _find(doc, given)
            if plan is None:
                lines.append(f"! no plan {_flat(given)} in this repo")
                continue
            picked.append(plan)
        plans = picked
    for plan in plans:
        lib, bad = _lib([plan])
        if bad:
            # A catalogue this plan links into is broken, which is a defect OF THIS PLAN
            # from where a lead is standing: the plan renders as nothing until it is fixed.
            lines.append(f"! {plan['id']} does not render — {bad.human}")
            found.append({"id": plan["id"], "file": _path(ctx, plan),
                          "defects": [str(bad.human)]})
            continue
        defects = _defects(_shown(plan, lib))
        found.append({"id": plan["id"], "file": _path(ctx, plan), "defects": defects})
        lines.extend(defects)
    bad_ones = [f for f in found if f["defects"]] + list(doc.get("broken") or ())
    if not lines:
        n = len(found)
        lines = [f"no defects in {n} plan{'s' if n != 1 else ''}"
                 if found else "(no plans to check)"]
    return Result(human="\n".join(lines),
                  data={"ok": not bad_ones, "plans": found,
                        "broken": doc.get("broken") or []})


def _path(ctx, plan: dict) -> Optional[str]:
    """The file this plan lives in — what a lead about to edit it needs to be told.

    Computed rather than stored, from the id and the state dir sb handed us, because the
    filename IS the id: `p-7.json` and nowhere else, which `_read_split` enforces.

    A store that has not been migrated has no such file — every plan is in one
    `plans.json` — so that is what it says, and it never invents a `p-<n>.json` that does
    not exist. Asked of the disk on the way out, after the write, so it answers about the
    shape the plan was actually filed in.
    """
    d = ctx.state_dir
    if not _split(d):
        return str(d / FILE)
    n = _num(_PLAN_ID, plan.get("id"))
    return str(d / f"p-{n}.json") if n is not None else None


# -- the step lifecycle --------------------------------------------------------
#
# Three verbs left, and every one of them is `_on_step` (or, where it addresses a plan, the
# same three moves written out): read, change the ONE step named, log, write. Nothing here
# rewrites a plan wholesale — a re-plan and a tick can land in either order and the loser
# is still in the file — and the single `_log` call per verb is why the changelog is the
# record of how the job ran rather than of what the file ended up looking like. The rest of
# what used to be here is a field in the file now; `_wrong` is where their checks went.


def tick(ctx, args) -> Result:
    """Done. The only verb that writes it, and nothing in sb writes it for a step.

    `sb done` does not reach this, no report ticks anything, and no verb here ticks a step
    as a side effect of another. A lead reads a child's report and decides; a confident
    child ticks its own. Both of those are a person or an agent typing this command, which
    is the whole point of progress never being inferred.
    """
    bad = _cap(args.reason)
    if bad:
        return bad
    return _on_step(ctx, args.step, "tick", args.reason,
                    lambda step, who: _progress(step, DONE, args.reason), unblocked=True)


def skip(ctx, args) -> Result:
    """Skipped, with the reason, in one call. `tick`'s sibling and the other way past.

    A verb rather than a field edit for the two reasons `tick` is one: it is frequent, and
    it is the agent that did — or did not do — the work that types it, where reshaping the
    plan is the owner's. A child that has just found a step unnecessary can say so without
    editing a file it is not allowed to edit.

    THE REASON IS REQUIRED, which is the one refusal here and the only thing this verb has
    that a hand-edit does not. A skip is a state with a sentence beside it and never an
    absence: without `why` the step draws red (`_wrong`), so a verb that let one through
    would be a verb whose whole output is a warning. Refused at the door instead, where the
    error message can say what to write.

    `--why` goes on the STEP, where it renders beside the state; `--reason` is the audit
    line every mutating verb carries into the changelog. They are usually the same sentence
    and are still two fields: one is what the step says now, the other is what happened.
    """
    why = str(getattr(args, "why", None) or "").strip()
    if not why:
        return _needs("--why", "a skip is a state with a sentence beside it, never an "
                               "absence — say what made this step unnecessary and it "
                               "renders next to the state")
    bad = _cap(why, args.reason)
    if bad:
        return bad
    return _on_step(ctx, args.step, "skip", args.reason,
                    lambda step, who: _progress(step, SKIPPED, why), unblocked=True)


def note(ctx, args) -> Result:
    """A free-text note, on a step or on the plan itself. The target says which.

    Both exist because the design names both moments: the lead as it creates the plan, and
    whoever finishes a step as it is ticked. A plan-level note is the one that has nowhere
    else to go — what the job turned out to be about, what was learned — and the analysis
    pass reads a record cold, so notes are most of what makes one worth reading at all.

    `p-1` is the plan; `s-1`, `step-1` and a bare `1` are the step. A bare number means a
    step here for the same reason it does everywhere else in this file: every other verb
    addresses a step by its number alone, and the one place that would read it as a plan is
    the place it would be a surprise.

    A SLASH SETTLES IT BEFORE THE PREFIX IS READ, because `p-16/step-3` starts with a `p`
    and is a step. The qualifier names the plan a step is in (see `_locate`), so the target
    it qualifies is never the plan itself.

    `--text` is the note; `--reason` is the audit reason every other mutating verb carries
    into the changelog, and it is here for the same reason it is there — a changelog whose
    entries mostly say why, with one verb's entries silent, reads as a gap in the record.
    """
    text = (args.text or "").strip()
    if not text:
        return _needs("--text", "a note is the text somebody reads back later")
    bad = _cap(text, args.reason)
    if bad:
        return bad
    target = str(args.target or "").strip()
    if "/" in target or not target.lower().startswith("p"):
        return _on_step(ctx, args.target, "note", args.reason,
                        lambda step, who: _add_note(step, text, who))

    doc, seal = _read(ctx.state_dir)
    plan = _find(doc, args.target)
    if plan is None:
        return _missing(doc, args.target)
    lib, bad = _lib([plan])             # before the write, so it cannot refuse after one
    if bad:
        return bad
    who = ctx.agent or "human"
    plan.setdefault("notes", []).append(_note(text, who))
    _log(plan, who, "note", args.reason, f"on {plan['id']}: {_clip(text)}")
    _write(ctx.state_dir, doc, seal)
    return _plan_result(_shown(plan, lib))


# -- the catalogue -------------------------------------------------------------
#
# Three verbs over two directories of JSON shipped beside this file. Read-only, all of them:
# `library` and `template list` render what is there, `name-step` and `template use` put
# LINKS and COPIES into the state file respectively, and nothing writes a definition.


def migrate(ctx, args) -> Result:
    """Move this repo's store from one `plans.json` to one file per plan. Once, by hand.

    A verb and not a thing that happens on its own, which is the whole design. The store
    belongs to the repo and every worktree in it shares one; the worktrees adopt a new
    plugin one at a time. A plugin that migrated the first time it read would flip the
    shape under every worktree still on the old code, and each of them would refuse every
    plans command until somebody noticed — which is exactly what happened the first time
    this was written, and why it is a verb now.

    So the warning is the output, not a footnote in it: this is a one-way door on shared
    state, and the person typing it is being asked to know that the fleet is ready. It is
    safe in the only sense that matters — no record is lost, the old file is kept — and
    unsafe in the sense that matters to whoever is mid-job on an old plugin.
    """
    moved = _migrate(ctx.state_dir)
    if moved is None:
        return Result(human=f"already one file per plan — nothing to move "
                            f"({len(_files(ctx.state_dir))} plans in {ctx.state_dir})",
                      data={"migrated": False, "plans": []})
    return Result(human="\n".join([
        f"moved {len(moved)} plan{'s' if len(moved) != 1 else ''} to one file each in "
        f"{ctx.state_dir}" + (f": {', '.join(moved)}" if moved else ""),
        f"the old file is kept as {MIGRATED} — no record was dropped",
        "",
        "THIS FLIPS THE STORE FOR THE WHOLE REPO. Every worktree still running the",
        "single-file plans plugin will now REFUSE every plans command against it, and",
        "its board will draw no plans, until it is on this version. If any worktree is",
        f"still on the old plugin, put {MIGRATED} back as {FILE} and delete the",
        f"p-<n>.json files and {META} — that undoes this exactly, losing nothing."]),
        data={"migrated": True, "plans": moved, "kept": str(ctx.state_dir / MIGRATED)})


def library(ctx, args) -> Result:
    """Browse the definitions a plan can name, or read one of them in full.

    Browsable for the same reason templates are: nobody knows at the start of a job which
    steps already exist, and a catalogue you have to know the contents of before you can
    look at it is a catalogue nobody uses. It may be nearly empty and that is expected —
    the design says what belongs in it is read off real runs, not decided up front.
    """
    lib, bad = _lib()
    if bad:
        return bad
    wanted = [str(n).strip() for n in (args.name or ()) if str(n).strip()]
    for name in wanted:
        if name not in lib:
            return _no_def(lib, name)
    picked = {k: lib[k] for k in wanted} if wanted else lib
    if not picked:
        return Result(human="(the step library is empty — every step is invented on the "
                            "fly, which is a shape this design expects)", data={})
    try:
        # The one place a malformed `steps` or `obliges` is READ without being expanded,
        # so it is also the one read-only verb that can meet one. Refusing here is right:
        # this verb's whole subject is the catalogue, so a broken file in it is the answer
        # rather than an interruption — and it is a refusal, not an escaped exception.
        human = "\n".join(_def_lines(k, picked[k], lib, full=bool(wanted)) for k in picked)
    except _BadDef as e:
        return e.refusal()
    return Result(human=human, data=picked)


def name_step(ctx, args) -> Result:
    """Name a library step into a plan: a link to its definition, and its own run object.

    The plan stores `def` and leaves `name` null, so the text comes out of the library
    every time the plan is rendered and an edit to a definition reaches this plan even
    while it is running. Copying the name in here would be the same code with the design's
    central claim quietly deleted from it.

    What lands may be more than one step. A composite expands flat, and whatever the
    resulting steps oblige is added beside them — which is the whole of "obliged, not
    optional": there is no argument to this verb that turns it off, and the merge step and
    its review are added by the same act.
    """
    wanted = str(args.name or "").strip()
    if not wanted:
        return _needs("name", "a named step is named after a definition in the library")
    bad = _cap(wanted, args.reason)
    if bad:
        return bad
    lib, bad = _lib()
    if bad:
        return bad
    if wanted not in lib:
        return _no_def(lib, wanted)
    # The DEFINITION's display, since that is where a named step's board label lives and
    # where an edit to it has to reach every plan naming it. So this refusal is about the
    # catalogue rather than about the command: there is no argument here that could supply
    # one, and a copy of the label on the step would be the link quietly turned into a copy.
    if not str((lib.get(wanted) or {}).get("display") or "").strip():
        return _no_display(f"the '{_flat(wanted)}' definition",
                           f"A named step draws its definition's label, so add a "
                           f"`display` to `library/{_flat(wanted)}.json`.")

    # NO LOCK: the step id comes from this plan's own counter in this plan's own file, so
    # the only race left is two writers on one plan — which the design answers with one
    # writer per plan rather than with a lock. See `_minting`.
    doc, seal = _read(ctx.state_dir)
    plan = _find(doc, args.plan)
    if plan is None:
        return _missing(doc, args.plan)
    try:
        added = _mint(plan, lib, wanted, after=tuple(_sinks(plan)))
    except _BadDef as e:
        return e.refusal()
    plan.setdefault("steps", []).extend(added)
    who = ctx.agent or "human"
    _log(plan, who, "name-step", args.reason, _minted(added, lib))
    _write(ctx.state_dir, doc, seal)
    return _added(plan, added, lib)


def template(ctx, args) -> Result:
    """`list` browses the preconfigured plans; `use` copies one into a plan of your own.

    Copy and paste, in the ordinary sense of the word, and nothing links the copy back —
    there is no field naming the template, and deleting the template file afterwards
    changes nothing about a plan made from it. The changelog says where it came from
    because that is the story of how the job ran, which is not the same as a reference the
    copy resolves through.

    What the copy DOES carry is the links: a named step inside a template stays a name, so
    it is still resolved live and still obliges what it obliges. Copies and links point
    opposite ways, and a template that flattened its names into copies would be the design's
    two mechanisms collapsed into one.
    """
    kept, bad = _kept()
    if bad:
        return bad
    wanted = " ".join(str(w) for w in (args.name or ())).strip()
    if args.action == "list":
        if not kept:
            return Result(human="(no templates — a plan starts empty or from `create`)",
                          data={})
        return Result(human="\n".join(_template_lines(k, kept[k]) for k in kept), data=kept)

    if not wanted:
        return _needs("name", "`template use` copies one template; `template list` shows "
                              "which are there")
    if wanted not in kept:
        # Escaped for the same reason `_no_def` is: the name arrives uncapped and the
        # keys are filenames.
        why = (f"no template '{_flat(wanted)}'"
               + (f" — there is {', '.join(_flat(k) for k in kept)}" if kept
                  else " — there are none"))
        return Result(ok=False, human=why, data={"error": why, "name": wanted})
    spec = kept[wanted]
    title = (args.title or spec.get("title") or "").strip()
    display = (args.display or spec.get("display") or "").strip()
    bad = _cap(title, display, args.reason)
    if bad:
        return bad
    if not display:
        return _no_display(f"the '{_flat(wanted)}' template",
                           f"It is the copy's board header, so give the copy one with "
                           f"`--display`, or add a `display` to "
                           f"`templates/{_flat(wanted)}.json`.")

    lib, bad = _lib()
    if bad:
        return bad
    # THE ONE LOCK LEFT, and it is held over this and nothing else: minting. See
    # `_minting` for why the other verbs need none and what is left unguarded.
    with _minting(ctx.state_dir):
        doc, seal = _read(ctx.state_dir)
        who = ctx.agent or "human"
        where, how = _workspace(ctx)
        plan = {"id": f"p-{doc['next_plan']}", "workspace": where, "workspace_from": how,
                "checkout": str(_here(ctx)), "title": title, "display": display,
                "next_step": 1, "steps": [], "changelog": [],
                "notes": [_note(str(n).strip(), who) for n in (spec.get("notes") or ())
                          if str(n).strip()],
                "created_by": who, "created_at": int(time.time())}
        doc["next_plan"] += 1
        try:
            # ONE ENTRY AT A TIME, EACH LANDING BEFORE THE NEXT IS EXPANDED, because an
            # anchor is read against the plan as it stands (`_place`) and a copy built with
            # every entry expanded against an empty plan gave every anchored step nothing to
            # be placed against: a template naming `create-pr` after its implementation
            # entries put the change approval AFTER the implementation, which is the one
            # defect anchors exist to remove, and marked it a root that `_chain` then wrote
            # an edge onto. The entries' own order is still `_chain`'s to draw; what this
            # buys is that an entry sees the entries before it.
            entries = list(spec.get("steps") or ())
            landed: list[list[dict]] = []
            for n, e in enumerate(entries):
                made = _from_template(plan, lib, e)
                plan["steps"].extend(made)
                landed.append(made)
                _chain_entry(entries, landed, n)
        except _BadDef as e:
            return e.refusal()

        detail = f"from {wanted}: {_minted(plan['steps'], lib) or 'empty'}"
        if how == UNAVAILABLE:
            detail += "; workspace unresolved — sb did not answer"
        _log(plan, who, "template", args.reason, detail)
        _reserve(ctx.state_dir, doc, plan)          # the id, claimed; see `create`
        doc["plans"].append(plan)
        _write(ctx.state_dir, doc, seal)
    return _plan_result(_shown(plan, lib), path=_path(ctx, plan))


def _sinks(plan: dict) -> list[str]:
    """The ids a plan currently ENDS with: its steps that nothing else waits for.

    What a step added to a running plan comes after, unless its author says otherwise. Read
    by number like every other id comparison here, so a hand-edited `deps: [1]` counts as
    the edge it is and its target is not reported as a loose end.

    Several, in a plan that forked and never joined, and the answer is then all of them: a
    step added to a plan with two open ends waits for both, which is the join a lead would
    have written and is reshaped in the file where it is not what they meant.
    """
    steps = plan.get("steps") or []
    waited: set[int] = set()
    for st in steps:
        for d in st.get("deps") or ():
            n = _num(_STEP_ID, d)
            if n is not None:
                waited.add(n)
    return [str(st.get("id")) for st in steps
            if _num(_STEP_ID, st.get("id")) not in waited and st.get("id")]


def _chain(entries: Any, landed: list[list[dict]]) -> None:
    """A template's `after` — the order between its entries — as deps on the steps it made.

    ONE ENTRY IS NOT ONE STEP, which is the whole reason this is not a two-line loop: a
    `def` entry expands to a definition, whatever it composes and whatever those oblige,
    and the order the template author wrote is between the ENTRIES they can see. So an
    entry's `after` attaches to that entry's own roots — the steps its expansion left with
    no dep — and points at the previous entry's sinks, the steps nothing inside it waits
    for. A plain one-step entry is the same rule with one step at each end.

    `after` holds entry POSITIONS, 1-based, as they are written in the file: a template is
    a short hand-written list and its entries have no ids to name each other by. Out of
    range or pointing forwards is refused, because an edge to nothing renders as an order
    that silently is not there.

    A MARKED ROOT IS NOT ONE OF AN ENTRY'S ROOTS. A step placed by its anchor with nothing
    lower than it in the plan says so with `root: true` — a change approval runs before the
    work whatever entry brought it — and an entry's `after` written onto that step would
    both contradict the mark and re-create the order the anchor exists to fix. It is a
    start, so nothing is written onto it; the entry's other rootless steps take the edge.

    ONE ENTRY AT A TIME (`_chain_entry`), because `template` lands each entry before the
    next is expanded so that an anchor has the entries before it to be placed against. An
    entry's edges have to be drawn in that same round: a `review` expanded while the entry
    before it still had no edges saw two implementation steps that both looked like sinks
    and waited on both. `after` only ever points backwards, so an entry can always be
    chained the moment it lands.
    """
    for n in range(len(list(entries))):
        _chain_entry(entries, landed, n)


def _chain_entry(entries: Any, landed: list[list[dict]], n: int) -> None:
    """One entry's `after`, drawn as soon as that entry has landed. See `_chain`."""
    entries = list(entries)
    entry = entries[n]
    after = (entry or {}).get("after") if isinstance(entry, dict) else None
    if after:
        # The roots are read ONCE, before any of this entry's edges are added. Asking
        # "which steps have no deps yet" inside the loop made the second `after` a no-op —
        # the first edge filled the field the second was testing — so a join written as
        # `"after": [1, 2]` silently recorded one of its two edges.
        roots = [st for st in landed[n] if not st["deps"] and not st.get("root")]
        for given in after:
            try:
                j = int(given)
            except (TypeError, ValueError):
                raise _BadDef(f"a template's `after` holds entry numbers, not {given!r}")
            if not 1 <= j <= len(landed) or j - 1 >= n:
                raise _BadDef(f"a template's step {n + 1} comes after {j}, which is not "
                              f"an earlier entry in it")
            waited = [st["id"] for st in landed[j - 1]
                      if not any(st["id"] in x["deps"] for x in landed[j - 1])]
            for st in roots:
                st["deps"] += [w for w in waited if w not in st["deps"]]


def _from_template(plan: dict, lib: dict, entry: Any) -> list[dict]:
    """One template entry, as the steps it puts in the copy. A name, or a link.

    An entry that says `def` is a link and goes through the same expansion `name-step`
    does — obligations included, since a template naming a merge and forgetting its review
    is exactly the memory this obligation exists to replace.

    Either way the entry's remaining keys are written onto the step it made (`_written`),
    which is how a template authors a gate, an owner or a checkpoint on a step that has no
    verb to write one.
    """
    if not isinstance(entry, dict):
        raise _BadDef(f"a template's steps are objects, not {type(entry).__name__}")
    key = str(entry.get("def") or "").strip()
    if key:
        if key not in lib:
            raise _BadDef(f"a template names '{key}', which is not in the step "
                          f"library")
        made = _mint(plan, lib, key)
        for st in made:
            k = _defkey(st) or ""
            if not str((lib.get(k) or {}).get("display") or "").strip():
                raise _BadDef(f"a template names '{k}', which has no `display` — a named "
                              f"step draws its definition's board label, so add one to "
                              f"`library/{k}.json`")
        # The entry's own step is the first one its expansion minted; what it obliged is
        # its own step and carries none of this. A gate written against `merge` belongs to
        # the merge and not to the human review that came along with it.
        _written(plan, entry, made[0])
        return made
    name = str(entry.get("name") or "").strip()
    if not name:
        raise _BadDef("a template holds a step with neither a name nor a def")
    # A template's own step carries its `display` into the copy, since a template writes the
    # long name and so is exactly where a short board label is worth authoring — and it is
    # required here for the same reason it is required of `create`: a template is where a
    # plan's steps are authored, and the shipped copy of one is what everybody starts from.
    # A `def` entry writes none — its display resolves live from the definition, like its
    # name — and is checked against the library above instead.
    display = str(entry.get("display") or "").strip()
    if not display:
        raise _BadDef(f"a template step '{name}' has no `display` — the board draws that "
                      f"label in its cell, and a step without one falls back to the whole "
                      f"sentence")
    made = _step(_mint_step(plan), name, display=display)
    _written(plan, entry, made)
    return [made]


# The keys a template entry owns rather than the step it mints: the two the grammar of a
# template is written in, the two read above, and the two the minter writes. Everything
# else on an entry is a field on the step.
_ENTRY = frozenset({"after", "def", "name", "display", "id", "deps"})


def _written(plan: dict, entry: dict, step: dict) -> None:
    """A template entry's remaining keys, written onto the step it minted.

    A template is where the shape of a plan is AUTHORED, so it has to be able to author
    more than a name. A gate, an owner, a checkpoint, a skip and its reason, a count of
    tries are fields on a step and none of them has a verb — a template that could carry
    only a name could not be a worked example of what a plan looks like, which is the one
    job the shipped template has.

    COPIED BLIND, in the same spirit `_markdown` is walked in: this function knows none of
    those fields by name, so a field added to a step next year is authorable in a template
    the day it exists. What it does know is `_ENTRY`, the six keys that are the template's
    own grammar or the minter's — `id` and `deps` especially, which a template writing
    would be overwriting the numbering and the edges `_chain` is about to draw.

    `notes` are the one shape converted rather than copied, exactly as a template's own
    plan-level notes are: a note is `{text, by, at}` and a template author writes the
    sentence. A list of bare strings copied through would render as a crash rather than as
    a note.
    """
    who = str(plan.get("created_by") or "human")
    for k, v in entry.items():
        if k in _ENTRY:
            continue
        if k == "notes" and isinstance(v, list):
            step[k] = [_note(str(n).strip(), who) for n in v if str(n).strip()]
        else:
            step[k] = v


def _on_step(ctx, given: str, action: str, reason: Optional[str], change,
             *, unblocked: bool = False) -> Result:
    """Read, change the one step named, log, write. Every step verb is this.

    `change` mutates the step and returns the changelog detail — or a `Result`, for the
    refusal it could not make before the file was read. Having one shape for all of them is
    what makes "every mutating verb appends a changelog entry" a property of the file
    rather than a thing nine verbs each remember: a verb that skipped `_log` would have to
    not be written this way at all.

    `unblocked` is what the two verbs that MOVE a step past ask for: what this move just
    released, printed under the result with its instructions in full. See `_next`.
    """
    doc, seal = _read(ctx.state_dir)
    plan, step = _locate(doc, given)
    if step is None:
        return _no_step(doc, given)
    lib, bad = _lib([plan])             # before the write, so it cannot refuse after one
    if bad:
        return bad
    who = ctx.agent or "human"
    detail = change(step, who)
    if isinstance(detail, Result):
        return detail                   # refused, and nothing has been written
    _log(plan, who, action, reason, detail)
    _write(ctx.state_dir, doc, seal)
    return _changed(plan, step, lib, _next(plan, step) if unblocked else [])


def _progress(step: dict, to: str, why: Optional[str]) -> str:
    """Move a step's progress, and say what it moved from. `tick` is what calls this.

    One field, so complete and skipped cannot both be true — whatever moves it second
    replaces the first rather than joining it, and the changelog is what says a correction
    happened. `why` is overwritten too, including with nothing: a step ticked after a skip
    must not keep the sentence explaining why it was skipped.
    """
    was = step.get("progress")
    step["progress"] = to
    step["why"] = (why or "").strip() or None
    return f"{step['id']} {was} → {to}"


def _add_note(step: dict, text: str, who: str) -> str:
    step.setdefault("notes", []).append(_note(text, who))
    return f"{step['id']}: {_clip(text)}"


def _next(plan: dict, moved: dict) -> list[dict]:
    """What moving this step past just released: the steps that can now be started.

    THE MOMENT A STEP IS PICKED UP is the only moment its instructions are worth printing,
    and it is the moment nothing used to mark. A definition's `about` — the two-section
    contract a change approval is written in, what a human-review list may and may not
    hold — is the whole of how that step is done right, and `_resolve` never carried it
    onto the step, so an agent met the step and not the instruction unless it already knew
    to go and read the definition. Which is a thing you only know to do once you have got
    it wrong. So it arrives here instead, unasked, at the tick or the skip that hands the
    next step to somebody.

    RELEASED BY THIS MOVE and not merely open: a step is listed if it names the step that
    just moved among its deps AND every one of its deps is now done or skipped. Every open
    step whose deps happen to be clear would print the plan's whole loose parallel work at
    every tick, which buries the one thing this is for. A step nothing waits on releases
    nothing, and that is a plan whose edges are missing rather than a plan with no next
    step — `_defects` is the door that says so.

    A SKIP RELEASES exactly as a tick does, and both words are the same fact here: the
    step is not going to be worked again, so whatever waited on it is waiting no longer.
    A plan that skipped a step and printed nothing would leave its successor unclaimed.
    """
    steps = plan.get("steps") or []
    at = {_num(_STEP_ID, s.get("id")): s for s in steps}
    n = _num(_STEP_ID, moved.get("id"))
    done = {DONE, SKIPPED}
    out = []
    for st in steps:
        deps = [_num(_STEP_ID, d) for d in (st.get("deps") or ())]
        if n not in deps or str(st.get("progress") or "") in done:
            continue
        if all(str((at.get(d) or {}).get("progress") or "") in done for d in deps):
            out.append(st)
    return out


# -- refusals ------------------------------------------------------------------
#
# A failed `Result` carries its reason in `data` as well as in `human`, because sb prints
# only `data` under `--json` — so a reason that lives in `human` alone reaches a person and
# nobody else. The consumers this matters for are the ones a later PR writes: a board that
# shells out to render plans gets `ok:false` and, without this, nothing to render or log.


def _missing(doc: dict, given: str) -> Result:
    """No such plan. The id is escaped, and that is not decoration.

    Every OTHER text in this file reaches a refusal having been through `_cap`, which
    refuses a control character outright. An id never can: it is matched against `_PLAN_ID`
    and the refusal IS what happens when the match fails, so this is the one message built
    out of a value nothing has vetted. Unescaped, `sb plugin plans show $'p-2\\np-9  done'`
    forges a row in the error output — the same hole this PR closes for the rendering, one
    door along.
    """
    why = _no_such(doc, given)
    return Result(ok=False, human=why, data={"error": why, "id": given})


def _no_step(doc: dict, given: str, plan: Optional[dict] = None) -> Result:
    """No such step. The same shape as `_missing`, one id kind along.

    Steps are numbered PER PLAN, so "the highest is step-7" is only true of somewhere: this
    says which plan it looked in whenever it knows one — from a `p-16/step-3` qualifier, or
    from the plan a caller was already working in, which is what a qualified id hands it.
    Ids are never reused within a plan, so a step that is not there has never been there.

    The third miss is the one per-plan numbering introduces: a BARE id that more than one
    plan holds. That is not "no such step" and is not refused as one — it names the
    candidates and the qualified spelling, which is the whole recovery.
    """
    said = _flat(given)                 # see `_missing`: an id is never vetted text
    plan_id, sep, step_id = str(given or "").rpartition("/")
    if sep:
        plan = _find(doc, plan_id)
        if plan is None:
            why = _no_such(doc, plan_id)
            return Result(ok=False, human=why, data={"error": why, "id": given})
        said = _flat(step_id)
    n = _num(_STEP_ID, step_id if sep else given)
    if n is None:
        why = f"'{said}' is not a step id — they look like step-1"
    elif plan is None and len(_holders(doc, n)) > 1:
        named = ", ".join(_flat(p.get("id")) for p in _holders(doc, n))
        why = (f"step {said} is in {named} — step numbers start again in every plan, so "
               f"name the plan: `{_flat(_holders(doc, n)[0].get('id'))}/{said}`")
    else:
        where = f" in {_flat(plan.get('id'))}" if plan is not None else ""
        high = _high(_STEP_ID, (st.get("id") for st in
                                ((plan.get("steps") or ()) if plan is not None else
                                 (s2 for p in doc["plans"] for s2 in (p.get("steps") or ())))))
        why = (f"no step {said}{where} — none has been made yet" if not high
               else f"no step {said}{where} — the highest there is step-{high}"
               if plan is not None else f"no step {said} — the highest is step-{high}")
    return Result(ok=False, human=why, data={"error": why, "id": given})


def _needs(what: str, why: str) -> Result:
    """A required argument that was not given, said with the reason it is required.

    Argparse cannot make an option mandatory through the four keys `reg.arg` exposes, and
    `--reason` on `skip` has to be mandatory — so the check is here. Saying WHY in the
    refusal is the point: an agent told only "--reason is required" supplies a word, and a
    skip reason nobody can read cold is the same as no skip reason at all.
    """
    why = f"{what} is required: {why}"
    return Result(ok=False, human=why, data={"error": why, "missing": what})


def _too_long(n: int) -> Result:
    why = (f"that is {n} characters; a plan's text is at most {MAX_TEXT}. Write the long "
           f"version somewhere a checkpoint can point at.")
    return Result(ok=False, human=why, data={"error": why, "length": n, "max": MAX_TEXT})


def _cap(*texts: Optional[str]) -> Optional[Result]:
    """What every verb checks about the text it was handed, before anything is read.

    Two rules, in one place because every verb wants both and a verb that remembered one
    of them is the shape this function exists to make impossible. `MAX_TEXT` is about a
    record staying readable when it is shown. The second is about a record being able to
    LIE when it is shown: a plan renders as rows and a row is a line, so a step named
    "write it\\ns-9  done  merged" draws a step nobody added, and an owner with a newline
    in it draws a status nobody read. Refused at the door, where the message can say what
    to do about it — and escaped again at the render, because a hand-edited file and a name
    in the library never came through here at all.
    """
    for text in texts:
        if not text:
            continue
        if len(str(text)) > MAX_TEXT:
            return _too_long(len(str(text)))
        if _CONTROL.search(str(text)):
            return _forged(str(text))
    return None


def _forged(text: str) -> Result:
    why = ("a plan's text is one line, and that has a newline or a control character in "
           "it. A plan renders as rows, so a field carrying one can draw a step, an owner "
           "or a status nobody wrote. Put the long version in a file and point a "
           "checkpoint at it.")
    return Result(ok=False, human=why, data={"error": why, "text": _clip(_flat(text))})


def _flat(text: Any) -> str:
    """Any stored text, as one line. The other half of `_cap`, and the load-bearing half.

    Every renderer in this file goes through this, including for text `_cap` never saw: a
    a plan file somebody edited by hand, and a `name` out of a definition in the library.
    Escaped rather than stripped, so what is there is still visible — a forged row shows up
    as the `\\n` it actually is, on the one line it was always entitled to.
    """
    return _CONTROL.sub(_escape, str(text))


def _lines(text: Any) -> list[str]:
    """`_flat`, one line at a time — the variant for the one field that is a BLOCK.

    Splits on the newline and then escapes each line, so the newline is the only control
    character spared and it is spared as a SEPARATOR rather than as content. Every renderer
    that uses this puts each line somewhere a forged row cannot reach — indented under a
    label in the terminal, blockquoted in markdown — so the property `_flat` holds
    everywhere else in this file is held here by where the lines go instead of by escaping
    them. Anything that is not a string is one line, which is the fallback: this is asked
    of a hand-edited field and must not raise on a list somebody put there.
    """
    return [_flat(line) for line in str(text).split("\n")]


def _escape(m: "re.Match") -> str:
    """One character, as the shortest spelling of it that is still text.

    `\\xNN` below U+0100 and `\\uNNNN` above it, because `\\x2028` would name a character
    that is not the one that was there — a message about a forgery that misnames the
    forgery is barely better than not saying.
    """
    c = m.group()
    if c in _ESCAPED:
        return _ESCAPED[c]
    return f"\\x{ord(c):02x}" if ord(c) < 0x100 else f"\\u{ord(c):04x}"


# -- the records ---------------------------------------------------------------


def _mint_step(plan: dict) -> str:
    """The next step id for ONE plan, from that plan's own counter. Never store-wide.

    Two plans are independent, so their step numbers are too: every plan starts at
    `step-1` and nothing another plan does moves it. The counter lives in the plan's own
    file, which is what makes that true across the split store — there is no shared number
    left for two worktrees to race for, and `name-step` needs no lock at all
    (see `_minting`).

    FLOORED ON READ by the plan's own highest step id, exactly as `next_plan` is floored by
    the ids on disk: a hand-deleted step, or a counter a hand-edit mangled, cannot make the
    next mint hand out a number this plan has already written down. Ids are still never
    reused within a plan, which is all `obliged_by`, `deps` and a changelog quoting one
    ever needed.

    Minted as `step-<n>`, which is what §3's markdown renders and what `_STEP_ID` reads
    back. A plan made before this carries `s-<n>` ids and keeps them — nothing is
    renumbered, because changelog entries quote ids as free text and rewriting history is
    the one thing the guide forbids. Such a plan simply mints its next step one past its
    own highest, in the new spelling; both spellings resolve.
    """
    n = max(_counter(plan.get("next_step")),
            _high(_STEP_ID, (s.get("id") for s in plan.get("steps") or ())) + 1)
    plan["next_step"] = n + 1
    return f"step-{n}"


def _step(sid: str, name: Optional[str], *, display: Optional[str] = None,
          key: Optional[str] = None, obliged_by: Optional[str] = None) -> dict:
    """One step, with every field the design names it carries and nothing more.

    `tries` starts at 1 rather than 0: a step being worked is on its first try, and a count
    above one is what renders. `deps` are the ids this step comes after — fan-out and join
    are edges the lead reads, never control flow anything executes. `why` is the reason for
    whatever `progress` currently says, and is here as an explicit null rather than a key
    that appears the first time something is skipped: the shape of a step is documented, and
    a field that exists only sometimes is a field every reader has to guess about.

    `gate` is the same, one field along: null on a step nobody has to be asked about, and
    the sentence saying what they have to answer on one where a human is the exit condition.
    Explicit here so that "this step has no gate" is a thing the record SAYS rather than a
    key it happens not to have — a reader deciding whether a plan has a gate at all should
    not have to tell a step made before this field existed from a step that has none.

    `output` is the step's own finished output — the one field here that is CONTENT rather
    than a reference, and it is that because the whole point of it is being dumped onto the
    pull request `create-pr` comments the plan onto. Multi-line by construction and longer
    than `MAX_TEXT`, so no verb writes it and it never goes through `_cap`: the agent that
    did the step writes it into the file by hand as it ticks, exactly as `gate` arrives.
    `--markdown` renders it as a quoted block rather than one escaped line (`_BLOCK`).
    Explicit null for the same reason `gate` and `why` are.

    `name` and `def` are the two ways a step says what it is, and exactly one of them is
    filled. An on-the-fly step owns its words; a named one owns a LINK, and its `name` stays
    null so that there is no copy of the definition here to go stale — the text is resolved
    at render time and an edit to the library reaches this step wherever it is. `obliged_by`
    is the id of the step that brought this one, which is how a review says which merge it
    belongs to and how PR7's gate will find it. Both are explicit nulls for the same reason
    `why` is.

    `display` is the short name the board draws, and it pairs with `name` exactly as they do:
    a named step leaves it null and resolves it live from the definition, an on-the-fly step
    carries its own. Explicit null, like `name`, so "this step has no shorter board label" is
    a thing the record says rather than a key it happens to lack — the board reads the field
    and falls back to the name when it is null.

    `root` is the one field here that exists to say a step is NOT missing something. A step
    with no `deps` past the plan's first start reads as a forgotten edge, and every one of
    them was reported as such — including the deliberate ones, so a plan whose two starts
    genuinely run side by side on disjoint work could only go green by inventing an edge
    that lied about the order. `root: true` is the lead saying "this start is meant", and
    it is a stored field rather than a guess because nothing about a bare `deps: []` can
    tell the two apart. False by default and explicit, like every null above: a step that
    is simply next in a chain says so.
    """
    return {"id": sid, "name": name, "display": display, "def": key,
            "obliged_by": obliged_by, "progress": OPEN, "why": None, "gate": None,
            "output": None, "owner": None, "tries": 1, "notes": [], "deps": [],
            "root": False, "checkpoints": []}


def _note(text: str, who: str) -> dict:
    return {"text": text, "by": who, "at": int(time.time())}


# -- the library and the templates ---------------------------------------------
#
# Read from disk on every command rather than cached in the module. sb runs one command per
# process so a cache would buy nothing real, and it would buy something wrong: a test — or a
# long-lived caller — that edits a definition and then renders a plan has to see the edit,
# because "editing a definition reaches every plan naming it" is the claim, not a hope.
#
# WHEN it is read is a correctness question rather than a performance one, and there are two
# rules. It is read only when something actually needs it — a plan with no links never
# touches the catalogue, so a typo in a JSON file cannot make an unrelated plan unreadable.
# And it is read BEFORE `_write`, never after: a verb that wrote and then failed to render
# would report a failure over a mutation that had already landed, and the agent that
# retried it would get a second plan or a second changelog entry. So `_lib` is called on the
# way in, its result is carried to the rendering, and nothing past `_write` can fail.


class _BadDef(ValueError):
    """A definition or a template this file cannot use, said so a machine reader hears it.

    An exception rather than a returned `Result` because it is raised three recursions deep
    inside expansion; `refusal()` is where it turns back into the plugin's normal shape.
    Every verb turns it back before it does anything else, which is why one of these can
    never escape as a bare plugin failure: escaping costs the `--json` payload PR4 and PR8
    read, and it costs it exactly when something is already wrong.
    """

    def refusal(self) -> Result:
        # Flattened at the one place every one of these turns into a message, because each
        # of them names a definition — and a definition is named after its FILE, which on
        # a POSIX filesystem may legally hold a newline or a tab.
        why = _flat(self)
        return Result(ok=False, human=why, data={"error": why})


def _lib(plans: Optional[list] = None) -> tuple[dict, Optional[Result]]:
    """The step library and a refusal, of which exactly one is real. Never raises.

    `plans` is what is about to be rendered: if not one of their steps is a link, the
    catalogue is not read AT ALL and a broken file in it cannot reach this command. That is
    the difference between refusing the verbs that resolve a definition — right — and
    refusing `show` on a plan that never named one, which would make a typo in a shipped
    JSON file take down every plan in the repo.

    `None` means the caller needs the library whatever the plans hold: `name-step`,
    `template use` and `library` itself.
    """
    if plans is not None and not any(_defkey(s) for p in plans
                                     for s in (p.get("steps") or ())):
        return {}, None
    try:
        return _catalogue(LIBRARY), None
    except _BadDef as e:
        return {}, e.refusal()


def _kept() -> tuple[dict, Optional[Result]]:
    """The templates, or a refusal. `_lib`'s shape, for the other directory."""
    try:
        return _catalogue(TEMPLATES), None
    except _BadDef as e:
        return {}, e.refusal()


def _names(key: str, spec: dict, field: str) -> list[str]:
    """A definition's list of names, refused rather than misread if it is a bare string.

    `"obliges": "merge-human-review"` iterates one letter at a time, and what came out of that
    was a refusal saying `'merge' obliges 'm', which is not in the step library` — technically
    a refusal, and useless to whoever has to fix the file.
    """
    given = spec.get(field)
    if given is None:
        return []
    if not isinstance(given, (list, tuple)):
        raise _BadDef(f"'{key}' has a '{field}' that is {given!r}; it is a list of "
                      f"definition names, and a bare string would be read one letter "
                      f"at a time")
    return [str(g).strip() for g in given if str(g).strip()]


def _catalogue(which: str) -> dict:
    """`library/` or `templates/`, as `{stem: spec}`. Missing is empty and empty is fine.

    Keyed on the FILENAME, so a definition is renamed by renaming its file and a plan
    linking to the old name says so plainly rather than resolving to something else. A
    directory that is not there at all is an empty catalogue and not an error: the design
    says the system must work with the catalogue almost bare, and a plugin that refused to
    run without one would be a catalogue nobody could ship without.

    A file that IS there and is not readable is refused, with its path, exactly as a
    plan's own file is. Silently skipping it would leave a plan resolving a link to nothing
    with no sign that the answer came from a typo in a JSON file.
    """
    d = Path(__file__).resolve().parent / which
    out: dict[str, dict] = {}
    try:
        files = sorted(d.glob("*.json"))
    except OSError:
        return out
    for f in files:
        try:
            spec = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError, OSError) as e:
            raise _BadDef(f"{f} is not readable JSON ({e}); fix it or move it aside") from e
        if not isinstance(spec, dict):
            raise _BadDef(f"{f} holds a {type(spec).__name__} where a definition should be")
        out[f.stem] = spec
    return out


def _flatten(lib: dict, key: str, path: tuple = ()) -> list[str]:
    """A definition as the flat list of definitions naming it puts in a plan.

    Composition is the one edge in this file that is TRAVERSED, and that is the whole reason
    a cycle in it is refused where a cycle in a plan's `deps` is not. Nothing walks a `dep`,
    so a cycle there is a lead's mistake to read; this walks, so a composite that reaches
    itself is a hang, and the refusal names the path so the file to fix is obvious.
    """
    if key in path:
        raise _BadDef(f"'{key}' composes into itself: {' → '.join((*path, key))}. "
                      f"Library composition is traversed, so a cycle in it cannot stand.")
    parts = _names(key, lib.get(key) or {}, "steps")
    if not parts:
        return [key]                     # a leaf: the definition itself is the step
    obliged = _names(key, lib.get(key) or {}, "obliges")
    if obliged:
        # An obligation attaches to a STEP — the design is explicit that what carries a skip
        # and what an obligation attaches to is always the step. A composite is not a step in
        # a plan; it never appears in one, only its parts do, so there is no step for
        # `obliged_by` to name and no honest place to hang this. Refused rather than dropped:
        # silently losing an obligation is the one failure the whole mechanism exists to
        # prevent, and dropping it is invisible to whoever wrote the file.
        raise _BadDef(f"'{key}' both composes ({', '.join(parts)}) and obliges "
                      f"({', '.join(obliged)}). An obligation attaches to a step, and a "
                      f"composite is not a step in a plan — put it on the part it "
                      f"belongs to.")
    out: list[str] = []
    for part in parts:
        if part not in lib:
            raise _BadDef(f"'{key}' composes into '{part}', which is not in the step "
                          f"library")
        out.extend(_flatten(lib, part, (*path, key)))
    return out


def _mint(plan: dict, lib: dict, key: str, after: tuple = ()) -> list[dict]:
    """The steps naming one definition puts in a plan: its expansion, then its obligations.

    Two walks. Composition expands first and may repeat a definition, because what a
    composite says is "this is several steps". Then every step that resulted is asked what
    it obliges, and it gets its own — ONE OBLIGED STEP PER OBLIGING STEP, with no dedupe of
    any kind. A composite naming `merge` twice is two merges and therefore two reviews, for
    the same reason naming `merge` twice in two separate acts is: two merges are two diffs,
    and a review that covered both is a lead's judgement to make by skipping one with a
    reason. Dedupe would make a step's obligation satisfiable by a step it has nothing to do
    with, which is the door round the obligation wearing a tidier shape.

    What stops that running forever is a cycle check rather than a dedupe: each step carries
    the chain of definitions that obliged it, an obligation reaching back into its own chain
    is refused with the path, and a chain therefore gains a definition it has not seen at
    every level. Obligation is traversed, so a cycle in it cannot stand — the same rule
    composition gets, for the same reason.

    Every id is minted from the one counter, in the order the steps will appear. Nothing is
    reused and nothing is renumbered, so `obliged_by` can point at a sibling by id.

    `after` is what the expansion HANGS OFF: the ids in the plan that nothing else already
    waits for, which `name-step` reads off the plan it is adding to. Without it the whole
    expansion lands as a second root — `name-step merge` on a plan with work in it drew a
    detached `review → merge` pair beside the chain and tripped the incompleteness door on
    the flagship path. Empty for a template, which records its own order (`_chain`), and
    empty for the first thing added to an empty plan, where a root is what this genuinely is.
    """
    wanted: list[tuple[str, Optional[int], tuple]] = [
        (k, None, ()) for k in _flatten(lib, key)]
    i = 0
    while i < len(wanted):
        k, _, chain = wanted[i]
        for ob in _names(k, lib.get(k) or {}, "obliges"):
            if ob == k or ob in chain:
                # `dict.fromkeys` for the path only: a step's chain ends with the definition
                # that obliged it, so writing it out beside `k` repeats one name. What is
                # wanted is the route, and a route says each stop once.
                route = " → ".join(dict.fromkeys((*chain, k, ob)))
                raise _BadDef(f"'{k}' obliges itself: {route}. "
                              f"An obligation is materialised when the step is added, so a "
                              f"cycle in one cannot stand.")
            if ob not in lib:
                raise _BadDef(f"'{k}' obliges '{ob}', which is not in the step library")
            wanted.extend((k2, i, (*chain, k, ob)) for k2 in _flatten(lib, ob))
        i += 1

    steps: list[dict] = []
    for k, by, _ in wanted:
        steps.append(_step(_mint_step(plan), None, key=k,
                           obliged_by=steps[by]["id"] if by is not None else None))
    _place(plan, lib, steps, after)
    return steps


def _place(plan: dict, lib: dict, steps: list, after: tuple) -> None:
    """The deps of a freshly minted expansion: where each of its steps RUNS.

    Two rules, and which one applies is decided per step by whether its definition carries
    an anchor (`_ANCHORS`, where the reasoning is).

    ANCHORED, and it lands after the sinks of the nearest lower band present in the plan.
    "Nearest" is the whole of it: a review named into a plan of implementation steps waits
    on the implementation and not also on the change approval two bands below it, which
    would draw a fan-in nobody wrote. A step with nothing lower than it anywhere in the
    plan is a start, and is MARKED one — a change approval added to a plan that already has
    work in it comes after nothing on purpose, and `root: true` is the difference between
    saying so and looking like a forgotten edge.

    UNANCHORED, and it keeps exactly the placement this file had before anchors: hung off
    `after`, the ids the plan currently ends with, with the obliging step waiting on what it
    obliged. A repo whose own library predates this goes on working, and a definition that
    genuinely has no fixed place in a job — most of them, in a catalogue that grows — is not
    made to invent one.

    THE OBLIGATION EDGE IS DRAWN ONLY FOR AN OBLIGED STEP THAT SAYS NOTHING ABOUT WHEN IT
    RUNS, which is the bug this function was written for. An anchored obliged step is
    placed by its anchor and the obligation then says only that the step exists; an
    unanchored one has nothing else to go on, so the edge is what it always was and the
    obliging step waits on it. `merge` obliging its human review comes out the same under
    either rule, which is the check that this is a fix and not a rewrite.

    The rule is about the OBLIGED end and not about both ends, and that is load-bearing: an
    unanchored step obliging an anchored one — `implement the thing` obliging `review`, the
    exact mixed library this function promises still works — drew the edge under a
    both-ends rule, and then placed the anchored step after the very step now waiting on it.
    Two steps, each waiting for the other, in a graph nothing traverses and nothing checks
    for cycles. The obliged end alone decides, so that can no longer be built.

    LOOKING BACKWARDS IS ALL AN ANCHOR DOES. A step is placed against the plan AS IT STANDS
    and nothing already in the plan is ever re-placed: this file's rule is that a command
    changes the steps it names, and silently rewriting deps a lead shaped by hand would be
    a worse bug than the one being fixed. So naming steps in separate calls, out of the
    order they run — `name-step merge` and then `name-step create-pr` — leaves the merge
    waiting on what the plan ended with at the time and not on the PR that arrived after
    it. `create --lib` sorts what it was given by anchor and is order-insensitive for that
    reason; `name-step` names one definition and cannot. Name them in the order they run,
    or make the plan in one `create`, and reshape in the file where you did neither.

    AND THEN THE OBLIGATION IS PUT BACK AS AN EDGE WHERE THE ANCHOR LEFT NONE, which is the
    half a first draft of this got wrong badly enough to lose a guardrail. `create-pr`
    obliges `change-approval`: the anchor correctly puts the approval at the very start,
    where nothing lower exists for it to come after — and it then sat there as a root that
    NO STEP IN THE PLAN LISTED, so the whole plan could be ticked to merged past an approval
    nobody had done, with `validate` silent. `obliged_by` is a label; only an edge is a
    wait. So after placement, an obliged step that nothing waits on gets its id appended to
    the deps of the step that obliged it — the PR waits on the approval AND on the review,
    the approval stays a marked early root, and "no PR without an approved contract" is in
    the graph again rather than in a field nothing reads.

    Two guards on that, both load-bearing. It is skipped where the obliged step ALREADY
    REACHES its obliger through the deps — `implement the thing` obliging `review` puts the
    review downstream, and a back-edge there is the round-one cycle rebuilt. And it writes
    only onto steps THIS COMMAND MINTED, never onto a step already in the plan, which is
    the same line every other write here keeps.
    """
    at = {st["id"]: st for st in steps}
    for st in steps:
        by = st.get("obliged_by")
        if by in at and not _anchored(st, lib):
            at[by]["deps"].append(st["id"])

    pool = list(plan.get("steps") or [])
    for i in sorted(range(len(steps)), key=lambda j: (_ranked(steps[j], lib), j)):
        st = steps[i]
        pool.append(st)
        if st["deps"]:
            continue                     # placed by the obligation edge above
        if not _anchored(st, lib):
            st["deps"] = list(after)
            continue
        rank = _ranked(st, lib)
        lower = [x for x in pool if x is not st and _ranked(x, lib) < rank]
        if not lower:
            st["root"] = True
            continue
        top = max(_ranked(x, lib) for x in lower)
        band = [x for x in lower if _ranked(x, lib) == top]
        # BY NUMBER, like every other id comparison in this file: a hand-written `deps: [1]`
        # is the edge it names, so the step it names is not reported as a loose end and
        # picked up as a second dep the plan already has transitively.
        waited = {_num(_STEP_ID, d) for x in pool for d in (x.get("deps") or ())}
        st["deps"] = [x["id"] for x in band
                      if _num(_STEP_ID, x["id"]) not in waited] or [band[-1]["id"]]

    waited = {_num(_STEP_ID, d) for x in pool for d in (x.get("deps") or ())}
    for st in steps:
        by = at.get(str(st.get("obliged_by") or ""))
        n = _num(_STEP_ID, st["id"])
        if by is None or not _owed(st, by, lib) or n in waited or _reaches(pool, st, by):
            continue
        by["deps"].append(st["id"])
        # The mark and an edge cannot both stand, which is the rule `_wrong` reports on a
        # hand-edit: a step that waits for something is not a start. Only reachable where
        # the two share a band, since a step with something lower than it in the plan was
        # never marked — but the write is what has to be consistent, not the argument.
        by["root"] = False
        waited.add(n)


def _owed(step: dict, by: dict, lib: dict) -> bool:
    """Should the step that obliged this one WAIT for it? The anchors decide, or nothing.

    `create-pr` obliges `change-approval` and runs three bands later, so the PR waits on
    the approval and that edge is the guardrail. `change-approval` obliges `review` and
    runs FOUR BANDS EARLIER, and the same edge there would say the approval waits on the
    review — the inversion anchors exist to remove, rebuilt by the mechanism that restores
    them. So the edge is owed only where the obliging step runs at or after the step it
    obliged; where it runs before, the obligation is satisfied by both steps being in the
    plan and the order is the anchor's to state.

    Equal ranks are owed, which covers every unanchored pair — two definitions with no
    anchor between them are exactly the case this file had before anchors, where the
    obliging step waited on what it obliged and nothing else said when either ran.
    """
    return _ranked(by, lib) >= _ranked(step, lib)


def _reaches(steps: list, frm: dict, to: dict) -> bool:
    """Does `frm` come after `to`, at any distance? The deps, walked once.

    The one place in this file that TRAVERSES a dep, and it is a question about a shape
    rather than a schedule: nothing here waits, and this is asked only to keep `_place`
    from drawing a back-edge over an order that already exists. Seen-set guarded, because
    a cycle in `deps` is a lead's mistake to read and must never be a hang here.
    """
    at = {_num(_STEP_ID, s.get("id")): s for s in steps}
    want, seen = _num(_STEP_ID, to.get("id")), set()
    queue = [_num(_STEP_ID, frm.get("id"))]
    while queue:
        n = queue.pop()
        if n == want:
            return True
        if n in seen or n not in at:
            continue
        seen.add(n)
        queue.extend(_num(_STEP_ID, d) for d in (at[n].get("deps") or ()))
    return False


def _anchor(lib: dict, key: str) -> int:
    """A definition's anchor as its position in `_ANCHORS`. Unanchored ranks with `build`.

    Refused rather than guessed at when it is a word the spine does not have: an anchor
    means its position and nothing else, so there is no position to fall back to and a
    typo would silently place the step somewhere plausible-looking instead.
    """
    given = (lib.get(key) or {}).get("anchor")
    if given is None or not str(given).strip():
        return _UNANCHORED
    word = str(given).strip()
    if word not in _ANCHORS:
        raise _BadDef(f"'{key}' has an anchor of '{_flat(word)}', which is not where "
                      f"anything runs — it is one of {', '.join(_ANCHORS)}")
    return _ANCHORS.index(word)


def _anchored(step: dict, lib: dict) -> bool:
    """Does this step's definition say where it runs? A step of its own words never does."""
    key = _defkey(step)
    return bool(key and str((lib.get(key) or {}).get("anchor") or "").strip())


def _ranked(step: dict, lib: dict) -> int:
    """Where a step in a plan sits on the spine. A step that owns its words is the work."""
    key = _defkey(step)
    return _anchor(lib, key) if key else _UNANCHORED


def _obliges(lib: dict, key: str) -> list[str]:
    """What naming this definition also adds. Safe after `_library` — see `_names`."""
    return _names(key, lib.get(key) or {}, "obliges")


def _defkey(step: dict) -> Optional[str]:
    """The definition a step links to, or None for one that owns its own words."""
    key = step.get("def")
    return str(key).strip() or None if key else None


def _resolve(step: dict, lib: dict) -> dict:
    """A step as it is READ: a linked one with its name filled in from the library.

    A copy, and only for rendering. The stored step keeps `name` null, which is what makes
    the link live — resolving into the record instead would be a snapshot, and the next edit
    to the definition would reach every plan except the ones already using it.
    """
    key = _defkey(step)
    if not key:
        return step
    spec = lib.get(key)
    if spec is None:
        return dict(step, name=f"{key} — no such definition in the library")
    # A definition that is there but names nothing renders as its own key rather than as
    # the sentence above: saying "no such definition" about a file sitting right there
    # sends whoever reads it looking for the wrong thing.
    #
    # `display` comes from the definition too, and is resolved here for the same reason
    # `name` is: it is part of what the library owns about a step, so an edit to the short
    # board label reaches every plan naming it. Null when the definition sets none, and the
    # board falls back to the name.
    #
    # `command` rides along for the same reason again, and for one more: the whole point of
    # it is that the agent working the step does not go looking for it. A field that only
    # showed up under `library <name>` would be a field you have to go and find, which is
    # the cost it exists to remove. Null when the definition sets none — most steps have no
    # single standard command, and an empty line under them would say there was one.
    #
    # `anchor` rides along too, and it is the one of these NOT put there to be read by a
    # person: `_wrong` has to know where a step runs to tell an obligation that was left out
    # of the order from one the anchors deliberately ordered the other way, and it is handed
    # a resolved plan and never the catalogue. Neither rendering a person reads prints it —
    # see `_MACHINERY`, which is where the two different ways that is arranged are — while
    # `--json` carries it, like everything else on the view. Where a definition runs is read
    # off `library <name>`, which says it in a word rather than in a field.
    return dict(step, name=str(spec.get("name") or "").strip() or key,
                display=str(spec.get("display") or "").strip() or None,
                anchor=str(spec.get("anchor") or "").strip() or None,
                command=str(spec.get("command") or "").strip() or None)


def _shown(plan: dict, lib: dict) -> dict:
    """A plan as it is read: the same record with every link resolved. Never written back.

    `lib` is passed rather than fetched, and that is the load-bearing part: this is called
    after `_write`, so a version of it that read the catalogue could turn a mutation that
    landed into a command that reported failure.
    """
    return dict(plan, steps=[_resolve(s, lib) for s in (plan.get("steps") or ())])


def _minted(steps: list, lib: dict) -> str:
    """What landed, for the changelog: the ids, what each is, and what obliged it."""
    bits = []
    for s in steps:
        bit = f"{s['id']} {_defkey(s) or s.get('name') or ''}".rstrip()
        if s.get("obliged_by"):
            bit += f" (obliged by {s['obliged_by']})"
        bits.append(bit)
    return ", ".join(bits)


# -- completeness: the display names and the deps the board draws with ---------
#
# THREE DOORS, and this is the machinery behind the second and third of them. A step
# without a display name and a step that says nothing about what it comes after are the
# two ways a plan renders as a column of half-sentences with no edges — which is what the
# board looked like before this, because nothing ever required either field.
#
# The first door is a refusal, and it is not here: `create`, `name-step` and
# `template use` will not MINT a step with no display name, and they say what a good one
# looks like when they refuse (`_no_display`). That door catches authoring.
#
# The second door is this one, and it WARNS AND STILL WRITES. Every other verb recomputes
# completeness after the write and appends what is wrong to what it prints. Never a
# refusal: a `tick` that will not land because of a rendering rule is worse than the
# rendering, and this is the door a hand-edited file arrives through — the plan file is
# meant to be edited by hand, so the requirement has to survive an author who never typed
# a verb at all.
#
# The third door is `show`, `list` and the board, which draw the defect on a plan nobody
# has run a verb against since. `board.py` reads `_defective` and paints those steps red.
#
# `_check` is deliberately NOT one of these doors. It refuses a FILE, and every plan
# written before this existed is missing both fields — a completeness rule wired into
# `_check` would take the board down to enforce a rendering preference. Structure is
# refused; completeness is reported and survivable, always.


def _faults(plan: dict) -> tuple[bool, list[str], list[str]]:
    """What is incomplete about a RESOLVED plan: the plan itself, then two lists of ids.

    Resolved (`_shown`) and not stored, which is the one thing a caller has to get right:
    a named step's `display` lives in its definition and its stored `display` is correctly
    null, so asking the stored step would report every library step in the store as
    defective and send a lead to fix a field that must stay empty.

    ONE ROOT IS FREE, and it is the first step that has no dep rather than the first step
    in the file. Those are usually the same step and sometimes are not: `name-step merge`
    lands the merge before the review it waits for, so the plan's only real start is second
    in the list, and a positional rule reported the flagship path as defective.

    A SECOND ROOT IS FREE TOO WHEN IT SAYS SO. `root: true` on the step is the lead saying
    the start is deliberate, and a marked root is no more incomplete than the first one is
    — a plan whose two starts genuinely run side by side is a shape this file draws, not a
    defect it paints red. Unmarked is still reported, because that is the case nothing can
    read: a bare `deps: []` is a forgotten edge and a parallel start in the same bytes, and
    the marker is the only thing that separates them. So the warning now has an answer that
    is not a false edge — the plan that was made red by two real starts used to be cleared
    by writing an order that never happened, which is a lie in the record to satisfy a
    rendering rule.
    """
    steps = plan.get("steps") or []
    nameless = [str(s.get("id") or "?") for s in steps
                if not str(s.get("display") or "").strip()]
    rootless = [str(s.get("id") or "?")
                for s in _rootless(steps)[1:] if not s.get("root")]
    return (not str(plan.get("display") or "").strip()), nameless, rootless


def _shown_rank(step: dict) -> int:
    """Where a RESOLVED step runs, read off the view rather than out of the catalogue.

    `_ranked` is the same question asked of a stored step and a library, and is what
    `_place` uses while it is minting. This one is for the doors, which are handed a
    resolved plan (`_shown`) and never a catalogue — see `_resolve`, which merges the
    anchor onto the view for exactly this. A step with none ranks as the work, as always.
    """
    word = str(step.get("anchor") or "").strip()
    return _ANCHORS.index(word) if word in _ANCHORS else _UNANCHORED


def _rootless(steps: list) -> list[dict]:
    """The steps with no dep, in file order. The first of them is the plan's start."""
    return [s for s in steps if not (s.get("deps") or [])]


def _wrong(plan: dict) -> list[tuple[str, str]]:
    """The rules the removed verbs used to keep, checked against the file instead.

    `gate`, `checkpoint` and `dep` each refused one thing before they were verbs nobody
    should have to type: a gate on a step already done, a checkpoint ref carrying a line
    break, an edge naming a step that is not there. A skip with no reason is the same rule
    from a verb that stayed, where it is a refusal at the door and this is what catches
    the same mistake written into the file. Those refusals were the whole of what those
    verbs bought
    over editing the field, and the rule has to outlive the verb or removing it would be
    removing the rule — so they live HERE now, in the warn door, and reach a hand-edit as
    well as a command, which the verbs never did.

    AN OBLIGATION WITH NO ORDER TO IT is the one rule here that no verb ever kept, and it
    is here because the anchor made it possible to lose one. An obliged step is added so
    that it CANNOT be omitted; a step sitting in the plan with no path to or from the step
    that obliged it is omitted in every way that matters. That is exactly the shape a first
    draft of `_place` produced for `change-approval`, and it is what a future anchor added
    to the catalogue could produce again.

    The condition is `_place`'s own, from the other side: nothing waits on the step, AND it
    does not come after the step that obliged it. Either one is enough to keep it in the
    job — something waiting on it means the plan cannot finish without it, and being
    downstream of its obliger means a tick releases it — and it is the plan with NEITHER
    that reads as finished with the obligation still open. Waited-on is the test rather
    than reaching the obliger in either direction, because a step and its obliger are often
    siblings under a third: the review and the change approval both hang under the PR that
    obliged one of them, with no path between the two. A done or skipped one is not
    reported, because a skip with its reason is the sanctioned way past an obligation.

    A WARNING AND NOT A REFUSAL, deliberately, for the same reason nothing else in this
    door refuses: the plan file is meant to be edited, and a file that bricks the board
    because one step's gate reads wrong is a file nobody dares open. Each one is
    `(step id, what is wrong)`, so the board can paint the step and `_defects` can name it.
    """
    out: list[tuple[str, str]] = []
    here_steps = plan.get("steps") or []
    here = {_num(_STEP_ID, s.get("id")) for s in here_steps}
    at = {_num(_STEP_ID, s.get("id")): s for s in here_steps}
    waited = {_num(_STEP_ID, d) for s in here_steps for d in (s.get("deps") or ())}
    for step in here_steps:
        sid = str(step.get("id") or "?")
        # THE EDGE THAT NAMES NOTHING, which was `dep`'s one refusal and is now the file's.
        # An edge whose target is not in this plan renders as a wait nobody is ever
        # released from, and a self-edge as a step waiting for itself; neither is a shape,
        # both are typos, and a typo in an id is exactly what an editor cannot see. Read
        # by NUMBER like every other id comparison here, so a hand-written `1` is the edge
        # it names rather than a fourth thing to warn about.
        mine = _num(_STEP_ID, step.get("id"))
        for d in step.get("deps") or ():
            n = _num(_STEP_ID, d)
            if n is not None and n == mine:
                out.append((sid, f"comes after itself ({_flat(str(d))}) — a step waiting "
                                 f"for its own completion is an edge nothing releases. "
                                 f"Point it at the step it really follows, or drop it."))
            elif n is None or n not in here:
                out.append((sid, f"comes after {_flat(str(d))}, which is not a step in "
                                 f"this plan — an edge to nothing draws as a wait that "
                                 f"never ends. Edges join steps of ONE plan, and nothing "
                                 f"here reads across plans."))
        by = at.get(_num(_STEP_ID, step.get("obliged_by")))
        if (by is not None and str(step.get("progress") or "") not in (DONE, SKIPPED)
                and _shown_rank(by) >= _shown_rank(step)
                and _num(_STEP_ID, step.get("id")) not in waited
                and not _reaches(here_steps, step, by)):
            out.append((sid, f"obliged by {_flat(str(step.get('obliged_by')))} and left out "
                             f"of the order — nothing in this plan waits on it and it comes "
                             f"after nothing that does, so the plan reads as finished with "
                             f"it still open. An obliged step is added so it cannot be "
                             f"omitted: put it in the chain, or skip it with the reason."))
        if step.get("root") and (step.get("deps") or []):
            # The two say opposite things about the same step, and the mark is the half a
            # reader trusts: `root: true` is somebody saying this start is deliberate, so a
            # step carrying one AND an edge reads as a start on the board and as a wait in
            # the file. The verb that wrote an edge used to clear the mark; this is that
            # rule where the edge is now written, which is by hand.
            out.append((sid, "marked a deliberate root and given a dep — a step that waits "
                             "for something is not a start. Drop the `root` or drop the "
                             "`deps`, whichever one is not true."))
        if str(step.get("gate") or "").strip() and str(step.get("progress") or "") == DONE:
            out.append((sid, "a gate on a step that is already done — a gate is reached "
                             "before the work it guards, so a plan does not get to mark "
                             "one already passed. Reopen the step, or record the skip and "
                             "the reason that cleared it."))
        skipped = str(step.get("progress") or "") == SKIPPED
        if skipped and not str(step.get("why") or "").strip():
            out.append((sid, "skipped with no reason — a skip is a state with a sentence "
                             "beside it, never an absence. Put the reason in `why`, where "
                             "it renders next to the state."))
        for cp in step.get("checkpoints") or []:
            ref = str((cp or {}).get("ref") or "") if isinstance(cp, dict) else str(cp)
            if _CONTROL.search(ref) or "|" in ref:
                out.append((sid, "a checkpoint that is not one line — a checkpoint is a "
                                 "reference (a path, a URL, an id) and never content, and "
                                 "a row on a board is a line. Write it to a file and point "
                                 "the checkpoint at the file."))
                break
    return out


def _defective(plan: dict) -> tuple[bool, set[str]]:
    """`_faults` as the board wants it: is the plan itself short, and which steps are.

    One set and not two, because red is red — a step drawn wrong is drawn wrong, and a
    board that coloured a missing display differently from a missing dep would be asking
    a glance to tell two shades apart to learn something the plan says in words.
    """
    short, nameless, rootless = _faults(plan)
    return short, set(nameless) | set(rootless) | {sid for sid, _ in _wrong(plan)}


def _defects(plan: dict) -> list[str]:
    """The same faults as lines to print under whatever the verb was doing.

    Names the ids and the fix, because a warning that says only "incomplete" is a warning
    whose reader has to go and diff the file against a rule they have not read. Every line
    is one thing wrong and the command that puts it right.
    """
    short, nameless, rootless = _faults(plan)
    wrong = _wrong(plan)
    if not (short or nameless or rootless or wrong):
        return []
    # "incomplete" while anything is MISSING, which is what the word means and what the
    # three doors were built for; "wrong" for the rules that came out of the removed verbs,
    # where the field is filled in and says something it may not. Both sentences end the
    # same way, because the promise is the same one: drawn red, and never refused.
    what = "is incomplete" if (short or nameless or rootless) else "has something wrong"
    out = [f"! {plan.get('id') or '?'} {what} — the board draws it red until this is "
           f"fixed, and nothing here refused the write"]
    if short:
        out.append("    the plan has no display name — the board draws its title instead. "
                   "A plan's display owns the whole header line, so it is a display "
                   "version of the title rather than an abbreviation of it.")
    if nameless:
        out.append(f"    no display name: {', '.join(nameless)} — the board draws a step's "
                   f"`display` in its cell, and a step without one falls back to the whole "
                   f"sentence. {_SHORTEN}")
    if rootless:
        out.append(f"    no dep: {', '.join(rootless)} — every step but the plan's first "
                   f"says what it comes after, or the board has no edge to draw and the "
                   f"plan renders as a loose stack. Fix: write `\"deps\": [\"<step>\"]` on "
                   f"{rootless[0]} in the plan file — or, if this start is deliberate and "
                   f"runs beside the plan's first, `\"root\": true`, which says so and is "
                   f"complete. Never an edge you do not mean.")
    out.extend(f"    {sid}: {why}" for sid, why in wrong)
    return out


def _plan_result(shown: dict, markdown: bool = False,
                 path: Optional[str] = None) -> Result:
    """A whole plan, printed, with anything incomplete about it said underneath.

    `path` is the file the plan was just filed in, and only the two verbs that MAKE a plan
    pass one. A lead's next move after `create` is to open the plan and shape it, and the
    id alone leaves it deriving a filename from a convention it has to have read first —
    so the command that made the file says where the file is, once, where the plan is.

    `ok` stays TRUE and `data` keeps its shape with one key added, which is the whole
    contract of the second door: a caller that was ticking a step ticked it, and a caller
    reading `--json` gets `incomplete` beside the plan rather than in place of it.

    `markdown` swaps the terminal rendering for the one that goes on a pull request, and
    swaps nothing else: `data` is the same record either way, so `--json` means what it
    always meant and a reader of it cannot tell which rendering was asked for. What is
    incomplete follows the plan into the markdown too — it is a key on the record by then,
    so the generic renderer picks it up without being told, which is the point of it.
    """
    lines = _defects(shown)
    doc = dict(shown, incomplete=lines) if lines else shown
    if path:
        doc = dict(doc, file=path)
    if markdown:
        return Result(human=_markdown(_dumped(doc)), data=doc)
    human = _full(shown) + ("\n\n" + "\n".join(lines) if lines else "")
    if path:
        human += f"\n\nthe plan is {path} — edit it there, then `sb plugin plans validate`"
    return Result(human=human, data=doc)


# What a refusal and a warning both say about shortening, written once. The example is the
# load-bearing half: an agent told "display is required" types the full name in again, and
# an agent shown `list every claim the document makes` → `list claims` has been told what
# the field is for. No length cap — a cap is what produced the half-sentences this
# replaced — so what stands in for one is this sentence and the author's judgement.
#
# SHORT BUT READABLE, and the examples are what enforce it. An earlier version of this
# asked for middle vowels to be dropped and got `invstgt` on real boards: shorter by four
# characters and no longer a word, which is a trade nothing was asking for. What actually
# shortens a label is cutting the words the plan's own title already says, since the title
# is on the header line directly above it.
_SHORTEN = ("Make it as short as it can be and still READ as words: abbreviate, and cut "
            "what the plan's own title already says — `list every claim the document "
            "makes` is `list claims`, `human review` is `review`. Short, not mangled: a "
            "label nobody can pronounce is not a label.")


def _no_display(what: str, how: str) -> Result:
    """A shape verb refusing to mint something with no display name. See `_SHORTEN`."""
    why = (f"{what} needs a display name — the short label the board draws for it. {how} "
           f"{_SHORTEN}")
    return Result(ok=False, human=why, data={"error": why, "missing": "display"})


def _authored(given: str) -> tuple[Optional[str], str]:
    """One `--step "list claims = list every claim it makes"`, split at the first `=`.

    ONE FLAG AND NOT TWO. `--step` repeats, so a parallel `--display` list would pair the
    two by position — and a list that is one short pairs every step after the gap with the
    wrong label, silently, in a field nobody re-reads. Written together they cannot desync.

    The first `=` and not the last, so a name containing one keeps it. Returns `(None, raw)`
    for a step written without a display name, which is what the caller refuses on.
    """
    if "=" not in given:
        return None, given.strip()
    display, name = given.split("=", 1)
    display, name = display.strip(), name.strip()
    return (display or None), name


def _log(plan: dict, who: str, action: str, reason: Optional[str], detail: str = "") -> None:
    """Append one changelog entry. The only way anything is ever added to a changelog.

    Every mutating command calls this, which is why it takes the reason as an argument
    rather than reading it off `args`: a verb that forgets to pass one is visible here as a
    `None` in the record, and a verb that forgets to call this at all is a diff nobody can
    miss.
    """
    plan.setdefault("changelog", []).append(
        {"at": int(time.time()), "by": who, "action": action,
         "reason": (reason or "").strip() or None, "detail": detail or None})


# -- the file ------------------------------------------------------------------


MINT = ".mint.lock"


@contextlib.contextmanager
def _minting(d: Path):
    """The one lock left: held while an id is allocated, and over nothing else.

    A PLAN id is minted from a counter that belongs to the whole store — `next_plan` in
    `_meta.json`, floored on read by the ids actually on disk — so two `create`s that read
    at the same instant read the same number and mint it twice. That is the one race
    per-file storage does not answer by itself, and it is not a race that fails quietly:
    the twin lands and `_check` refuses one of the two files on the next read, which costs
    a plan somebody just wrote. So it is prevented rather than detected, and the two verbs
    that allocate a plan id — `create` and `template use` — hold this across their read,
    their mint and their write.

    A STEP id needs none of it. It is minted from the plan's own counter in the plan's own
    file (`_mint_step`), so two agents minting steps in two plans never read one number,
    and two minting in ONE plan are two writers on one plan — the case below, which the
    design answers with a convention rather than a lock. `name-step` held this lock only
    for the store-wide step counter and holds nothing now.

    Every other verb takes nothing. `tick`, `skip`, `note` and every read run concurrently
    with each other and with an editor, which is the concurrency the per-file split was
    for.

    WHAT IS STILL UNGUARDED, said here rather than left to be discovered:

      - Two writers on ONE plan. The later read wins and the earlier write is lost, lock
        or no lock, because a hand-edit in an editor never took one. The answer is the
        design's convention — one writer per plan — and not a lock.
      - An UN-MIGRATED store, where every plan is in one `plans.json`. There, any two
        concurrent writes are two writers on one file, so the above applies to the whole
        repo rather than to one plan. That is the transitional cost of the old shape and
        the reason `migrate` exists; a store that has moved across does not have it.
      - A filesystem where `flock` does not work (some network mounts). `_reserve` is the
        second lock on the plan-id half of that door, and it needs no cooperation at all.
    """
    d.mkdir(parents=True, exist_ok=True)
    fd = os.open(d / MINT, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)                    # closing releases it


def _reserve(d: Path, doc: dict, plan: dict) -> None:
    """Claim the new plan's FILE before anything is written into it, or take the next one.

    `O_EXCL` is the whole mechanism: creating a file that already exists fails, so two
    processes racing for `p-3.json` cannot both have it and the loser moves to `p-4`. This
    is what makes a plan id safe without anybody's cooperation — no lock to take, no
    counter to agree on, and it holds against a plugin from another checkout, another
    version, or a filesystem where `flock` is a no-op.

    Written with the plan's final text rather than as an empty placeholder, so a crash
    between here and `_write` leaves a readable plan and not a zero-byte file the board
    would draw as broken. `_write` then writes the same bytes over the top, which costs
    one write and keeps the single write path the only thing that knows about seals.

    Nothing to do on an un-migrated store: there is no per-plan file to claim there, and
    the id comes back out of the one `plans.json` that `_minting` is serialising anyway.
    """
    if not _split(d):
        return
    d.mkdir(parents=True, exist_ok=True)
    while True:
        n = _num(_PLAN_ID, plan.get("id")) or 1
        try:
            fd = os.open(d / f"p-{n}.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            plan["id"] = f"p-{n + 1}"
            doc["next_plan"] = max(_counter(doc.get("next_plan")), n + 2)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(_text(plan))
        return


def _read(d: Path) -> tuple[dict, dict]:
    """The store, whichever shape it is in, and the seal `_write` checks against.

    TWO SHAPES, and which one is in use is read off the disk rather than off a version
    number: a directory holding `p-<n>.json` files or a `_meta.json` is a split store, and
    anything else — a single `plans.json`, or nothing at all — is the one-file store this
    plugin started with. Reading NEVER changes which; only `migrate` does.

    That is the whole of how a fleet crosses over. The store is shared by every worktree in
    a repo, and the worktrees update one at a time, so a plugin that flipped the shape the
    first time it read would take every worktree still on the old code down with it — which
    is exactly what an earlier version of this did. A new plugin on an un-migrated store
    reads and writes format 1 byte for byte, indistinguishably from an old one, for as long
    as it takes the fleet to catch up. Somebody then types `migrate`, once, deliberately.

    Never raises for a directory that is not there yet. The two counters are recomputed as
    floors over every id present, so a store that lost its counters still cannot mint an id
    that has already been written down somewhere else.
    """
    return _read_split(d) if _split(d) else _read_one(d)


def _split(d: Path) -> bool:
    """Is this store one file per plan? Asked of the disk, never of a version number.

    `_meta.json` is the flag, and `migrate` writes it LAST — after the legacy file has been
    moved aside — precisely so that this question has one answer at every instant of a
    migration. A version marker could not answer it: the whole point is that an un-migrated
    store keeps the format an older plugin reads, so the format says nothing about which
    shape is in front of you.

    PLAN FILES ALONE ARE NOT ENOUGH, and that is the crash this closes. `migrate` writes
    the per-plan files first; a crash there used to leave a store that read as split to
    this plugin while a complete format-1 `plans.json` sat beside it for every older one —
    two stores, each holding a different subset, and `migrate` refusing to re-run because
    it thought the job was done. So while a real single-file store is still present this
    says LEGACY, whatever else is in the directory: the half-written files are ignored, the
    plans are all read out of the file that still holds them, and re-running `migrate`
    finishes the job. The counters sidecar without them is still split — that is an empty
    store that migrated before its first plan.
    """
    if (d / META).exists():
        return True
    return bool(_files(d)) and not _legacy(d)


def _legacy(d: Path) -> bool:
    """Is a real single-file store sitting at `plans.json` — as opposed to the tombstone?

    The tombstone `migrate` leaves is a `plans.json` too (`_tomb`), stamped with a format
    an older plugin refuses, so the file EXISTING is not the question and its format is.

    A file that will not parse counts as one, deliberately: the alternative is reading past
    a store this plugin cannot make sense of and answering as if it were not there, and
    everything else in this file refuses rather than guesses when a record is unreadable.
    `_read_one` then gives the refusal, naming the path, which is the message a human can
    act on.
    """
    f = d / FILE
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except OSError:
        return False                    # not there at all, or unreachable
    except (ValueError, UnicodeDecodeError):
        return True                     # there and unreadable — see the docstring
    if not isinstance(doc, dict) or not isinstance(doc.get("plans", []), list):
        return True
    return _counter(doc.get("format", LEGACY_FORMAT)) <= LEGACY_FORMAT


def _read_one(d: Path) -> tuple[dict, dict]:
    """The single-file store, read the way it has always been read. Format 1, unchanged.

    A file that is there and unreadable is a REFUSAL, naming the path, rather than a fresh
    empty document: starting over would silently replace every plan in the repo on the next
    `create`, and the records are the whole point of keeping them. The failing verb stops,
    nothing is written, and a human fixes or moves the file. That one bad file costs every
    plan is the cost of the shape, and the reason `migrate` exists.

    Unreadable is checked all the way down, not just at the top level, and the reason is
    the seal rather than tidiness: it is keyed on the plan id, so two plans sharing an id —
    or two with no id at all — collapse into one entry and `_write`'s drop check passes
    over the plan that is no longer in it.

    `broken` comes back empty and not absent, so that nothing downstream has to know which
    shape it was handed: in this one, a plan that did not load means none of them did.
    """
    f = d / FILE
    if f.exists():
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise ValueError(f"{f} is not readable JSON ({e}); nothing here will overwrite "
                             f"it. Fix it or move it aside.") from e
        if not isinstance(doc, dict) or not isinstance(doc.get("plans", []), list):
            raise _refuse(f, "is not a plans file — a JSON object with a 'plans' list")
        if _counter(doc.get("format", LEGACY_FORMAT)) > LEGACY_FORMAT:
            # A single file stamped 2 is the tombstone `migrate` leaves behind, or a store
            # from a newer plugin. Either way this is not a file to read as plans, and
            # writing it back in this shape is how the plans beside it would be lost.
            raise _refuse(f, f"was written by a newer plans plugin (format "
                             f"{doc.get('format')}; a single-file store is format "
                             f"{LEGACY_FORMAT}, and one plan per file is what came after "
                             f"it — the plans may be the p-<n>.json files beside this)")
        _check_all(f, doc.get("plans") or [])
    else:
        doc = {"format": LEGACY_FORMAT, "next_plan": 1, "next_step": 1, "plans": []}
    doc.setdefault("format", LEGACY_FORMAT)
    doc.setdefault("plans", [])
    doc["broken"] = []
    plans = doc["plans"]
    doc["next_plan"] = max(_counter(doc.get("next_plan")),
                           _high(_PLAN_ID, (p.get("id") for p in plans)) + 1)
    doc["next_step"] = max(_counter(doc.get("next_step")),
                           _high(_STEP_ID, (s.get("id") for p in plans
                                            for s in (p.get("steps") or ()))) + 1)
    return doc, _seal(doc)


def _check_all(f: Path, plans: list) -> None:
    """One file's worth of plans, checked — the per-plan checks plus the two global ones.

    The single-file store cannot isolate anything: every plan in it shares one file, so a
    refusal is a refusal of all of them. What this does is run the same `_check` the split
    store runs per file, and then the one question no single plan can answer — a twin plan
    id — over the lot.

    A twin STEP id is not that question any more. Step numbers are minted per plan, so two
    plans in here both holding a `step-1` is the ordinary shape and not corruption; `_check`
    refuses the twin that still matters, which is two steps of ONE plan sharing a number.
    """
    seen: set[int] = set()
    for plan in plans:
        if not isinstance(plan, dict):
            raise _refuse(f, f"holds a {type(plan).__name__} where a plan should be")
        _check(f, plan)
        n = _num(_PLAN_ID, plan.get("id"))
        if n in seen:
            raise _refuse(f, f"holds two plans called p-{n}, and ids are never reused")
        seen.add(n)


def _read_split(d: Path) -> tuple[dict, dict]:
    """One plan per file, assembled. The shape `migrate` moves a store to.

    The point of it: an unreadable `p-7.json` costs p-7 and nothing else. It is left
    exactly where it is and listed in `doc["broken"]` for whoever is drawing; the other
    plans load and the board still shows them. A board that stopped drawing because one
    file was malformed would hide the nine things that are fine, and a verb that refused
    every plan because of one would too.

    Nothing here ever overwrites a file it could not read: a plan that did not load is not
    in `doc["plans"]`, so `_write` has nothing to write back over it, and `next_plan` still
    counts past it — its PLAN id is readable from the filename whether or not the contents
    are. Its step ids need no such reserving: they are minted from a counter inside that
    same file, so no other plan could hand them out however broken it is.

    The one invariant that does not fit in one file is checked here rather than in `_check`:
    a plan lives in the file its id names. A step id unique across the STORE was checked
    here too, once, and is gone with the store-wide counter — `tick step-3` names a plan
    when one holds it and refuses naming the candidates when several do (`_locate`), which
    is the UX contract that check was actually for.
    """
    meta = _meta(d)
    plans: list = []
    broken: list = []
    seen: dict[int, Path] = {}
    for f in _files(d):
        try:
            plan = _load(f)
            _check(f, plan)
            n = _num(_PLAN_ID, plan.get("id"))
            if n != _fnum(f):
                raise _refuse(f, f"holds p-{n}, and a plan lives in the file its id names")
            if n in seen:
                raise _refuse(f, f"holds p-{n}, which {seen[n].name} holds as well, and "
                                 f"ids are never reused")
        except ValueError as e:
            broken.append({"id": f"p-{_fnum(f)}", "file": str(f), "why": str(e)})
            continue
        seen[n] = f
        plans.append(plan)
    doc = {"format": FORMAT, "plans": plans, "broken": broken}
    doc["next_plan"] = max(_counter(meta.get("next_plan")),
                           max((_fnum(f) for f in _files(d)), default=0) + 1,
                           _high(_PLAN_ID, (p.get("id") for p in plans)) + 1)
    doc["next_step"] = max(_counter(meta.get("next_step")),
                           _high(_STEP_ID, (s.get("id") for p in plans
                                            for s in (p.get("steps") or ()))) + 1)
    return doc, _seal(doc)


def _files(d: Path) -> list[Path]:
    """The plan files, in id order. The one answer to "what plans exist".

    Sorted by number rather than by name, so the store is read in the order the plans were
    minted and `p-10` does not land between `p-1` and `p-2`. The glob is deliberately
    narrow — anything in this directory that is not `p-<digits>.json` (the lock, the meta
    file, a tmp file, an old store moved aside) is not a plan and is not read as one.
    """
    try:
        found = list(d.glob("p-*.json"))
    except OSError:
        return []
    return sorted((f for f in found if _fnum(f)), key=_fnum)


def _fnum(f: Path) -> int:
    """The plan number a filename claims, or 0 for a name that claims none."""
    return _num(_PLAN_ID, f.name[:-len(".json")]) or 0


def _load(f: Path) -> dict:
    """One plan file, parsed. Raises the refusal; the caller decides what it costs."""
    try:
        plan = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"{f} is not readable JSON ({e}); nothing here will overwrite "
                         f"it. Fix it or move it aside.") from e
    if not isinstance(plan, dict):
        raise _refuse(f, f"holds a {type(plan).__name__} where a plan should be")
    return plan


def _meta(d: Path) -> dict:
    """The counters sidecar, or an empty dict when there is nothing usable there.

    Missing or mangled is not a refusal, because it is not a record: everything in it is
    derivable from the plan files themselves, and `_read` takes the higher of what it says
    and what is actually on disk. The one thing it can refuse is a store from a newer
    plugin — the version marker lives here now that no single file carries it.
    """
    f = d / META
    try:
        m = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(m, dict):
        return {}
    if _counter(m.get("format", FORMAT)) > FORMAT:
        raise _refuse(f, f"was written by a newer plans plugin (format "
                         f"{m.get('format')}; this one speaks {FORMAT})")
    return m


def _migrate(d: Path) -> Optional[list[str]]:
    """The one-time move from a single `plans.json` to one file per plan.

    Reached ONLY from the `migrate` verb. Nothing that merely reads or writes calls this,
    which is the point: the store is shared by every worktree in the repo, and the shape it
    is in is what an older plugin can or cannot read. Flipping it is a decision somebody
    makes once the fleet is on this code, not a side effect of drawing a board.

    Whole, and then the old file is moved aside — to `plans.json.migrated`, not deleted,
    because records are kept and this is exactly the moment somebody would want it back.
    `None` for a store that is already split, so the verb can say so instead of pretending
    to have done something; otherwise the ids that moved.

    A legacy file that will not parse, or that holds a shape the split cannot represent —
    two plans claiming one id would collapse into one filename — is REFUSED rather than
    half-moved. Half a store in each shape is the one outcome worth failing loudly to
    avoid, and it is the same refusal `_read_one` gives for the same file.
    """
    if _split(d):
        return None
    legacy = d / FILE
    if not legacy.exists():
        # An empty store still moves: writing the counters is what puts it in the new
        # shape, so a repo that migrates before its first plan does not silently stay old.
        _atomic(d, META, _text({"format": FORMAT, "next_plan": 1, "next_step": 1}))
        _tomb(d)
        return []
    try:
        doc = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"{legacy} is not readable JSON ({e}); nothing here will "
                         f"overwrite it. Fix it or move it aside.") from e
    if not isinstance(doc, dict):
        raise _refuse(legacy, "is not a plans file — a JSON object with a 'plans' list")
    if "plans" not in doc or not isinstance(doc["plans"], list):
        raise _refuse(legacy, "is not a plans file — a JSON object with a 'plans' list")
    if _counter(doc.get("format", LEGACY_FORMAT)) > LEGACY_FORMAT:
        raise _refuse(legacy, f"is not a single-file store to move (format "
                              f"{doc.get('format')}; a single-file store is format "
                              f"{LEGACY_FORMAT})")
    # The same check the single-file store is read under, run before anything is written:
    # a twin plan id would collapse two plans into one filename and lose one of them.
    _check_all(legacy, doc["plans"])
    seen = {_num(_PLAN_ID, plan["id"]) for plan in doc["plans"]}
    steps_seen = {_num(_STEP_ID, step.get("id")) for plan in doc["plans"]
                  for step in plan.get("steps") or ()}
    for plan in doc["plans"]:
        # The plan as it stands, byte for byte through `json.dumps` — the changelog comes
        # across whole because nothing here reads it, edits it, or rebuilds it.
        _atomic(d, f"p-{_num(_PLAN_ID, plan['id'])}.json", _text(plan))
    # THE ORDER OF THESE FOUR LINES IS THE WHOLE CRASH SAFETY, and it is the reverse of
    # the obvious one. `_split` calls a store split when the counters sidecar is there, so
    # the sidecar is written LAST — after every plan file has landed and after the legacy
    # store has been moved aside. A crash anywhere before that leaves a directory that
    # still reads as legacy (`_split` ignores plan files while a format-1 `plans.json` is
    # present), so this plugin and an older one see the same complete store and re-running
    # `migrate` finishes the job. Writing it first left half a store in each shape, which
    # is the one outcome this verb exists to avoid.
    os.replace(legacy, d / MIGRATED)
    _tomb(d)
    _atomic(d, META, _text({
        "format": FORMAT,
        "next_plan": max(_counter(doc.get("next_plan")), max(seen, default=0) + 1),
        "next_step": max(_counter(doc.get("next_step")), max(steps_seen, default=0) + 1)}))
    return [f"p-{n}" for n in sorted(seen)]


def _refuse(f: Path, what: str) -> ValueError:
    """The one refusal, so every malformed file says the same two things.

    Returned rather than raised, so the caller reads as `raise _refuse(...)` and nothing
    can call this and carry on. What it says is the path and that the file is safe: a
    message that only says "no" sends a human looking for a bug in sb.
    """
    return ValueError(f"{f} {what}. Nothing here will overwrite it — fix it or move it "
                      f"aside.")


def _check(f: Path, plan: dict) -> None:
    """Every shape inside ONE plan that the rest of this module assumes, checked once.

    Per file, which is what makes a broken plan cost only itself: this raises about the
    one plan it was handed and `_read` drops that file alone. What it cannot see from
    here — a twin plan id, a step id another file also claims — is checked by `_read`
    over the assembled store, because neither question can be answered from one file.

    The plan id is checked for BEING there and for being a number, because both are load
    bearing: the seal is keyed on it, `_write` decides a plan was dropped by looking it up,
    and the filename is derived from it. Compared as numbers, so `p-1` and a bare `1` are
    the one plan they name rather than two rows that pass a string comparison.

    Every container a verb APPENDS to is checked for being a list, for the same reason the
    ids are: not tidiness, but that the code after this point assumes it. A `notes` that is
    null gives a raw `AttributeError` naming no file instead of the refusal this function
    exists to give, and a `deps` that is a string is worse than a crash — `in` degrades to a
    substring test, so `s-1` reads as already present in `"s-10"` and the edge is silently
    dropped. Refusing here is refusing before anything is written.
    """
    n = _num(_PLAN_ID, plan.get("id"))
    if n is None:
        raise _refuse(f, f"holds a plan with no usable id ({plan.get('id')!r})")
    steps = plan.get("steps", [])
    if not isinstance(steps, list) or any(not isinstance(s, dict) for s in steps):
        raise _refuse(f, f"has a p-{n} whose steps are not a list of steps")
    steps_seen: set[int] = set()
    for step in steps:
        # A twin `s-1` would take a tick meant for the other one and neither would say so;
        # a step with no id cannot be ticked at all. Everything past PR1 addresses a step
        # by its number alone, which is why this is checked and not merely rendered.
        m = _num(_STEP_ID, step.get("id"))
        if m is None:
            raise _refuse(f, f"has a step in p-{n} with no usable id "
                             f"({step.get('id')!r})")
        if m in steps_seen:
            raise _refuse(f, f"holds two steps called s-{m}, and ids are never reused")
        steps_seen.add(m)
        for key in ("deps", "notes", "checkpoints"):
            if not isinstance(step.get(key, []), list):
                raise _refuse(f, f"has an s-{m} whose {key} are not a list")
        # The two fields that are looked up rather than merely rendered: `def` keys the
        # library and `obliged_by` names a step. A dict in either renders as itself and
        # resolves to nothing — `s-1 open {'oops': 1} — no such definition` is not a
        # message anybody can act on, and this is where the file gets refused instead.
        for key in ("def", "obliged_by"):
            if step.get(key) is not None and not isinstance(step.get(key), str):
                raise _refuse(f, f"has an s-{m} whose {key} is not a name")
    for key in ("changelog", "notes"):
        if not isinstance(plan.get(key, []), list):
            raise _refuse(f, f"has a p-{n} whose {key} is not a list")


def _counter(given: Any) -> int:
    """A stored counter, or 1 if a hand-edit left something that is not a number there.

    1 is safe because it is a floor and not the answer: `_read` takes the higher of it and
    one past the highest id actually present, so a mangled counter costs nothing and a
    mangled counter that also refused to run would cost the plan.
    """
    try:
        return max(1, int(given))
    except (TypeError, ValueError, OverflowError):
        return 1


def _text(obj: Any) -> str:
    """One file's worth of JSON. The single speller, so `_seal` and `_write` agree.

    They have to agree byte for byte: `_write` decides a plan was not touched by comparing
    what it would write against what `_read` saw, and a second speller would make every
    plan look dirty and rewrite the whole store on every tick — the thing this layout
    exists to stop.
    """
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def _seal(doc: dict) -> dict:
    """Every loaded plan as it stands, keyed by plan NUMBER. Compared on the way out.

    The plan as TEXT, which `_write` compares to decide whether this file needs writing at
    all: a plan nobody touched is a file nobody rewrites. It sealed the changelog beside it
    once, for an append-only check `_write` no longer makes — see there for why that rule
    went — and what remains is which plans were loaded, which is what stops one being
    dropped.

    The number rather than the string, so that `p-1` and a bare `1` cannot seal one plan
    and be looked up as another. `_read` has already dropped a file where two plans share
    one, which is what makes a dict safe to key on it at all.
    """
    return {_num(_PLAN_ID, p.get("id")): {"raw": _text(p)} for p in doc["plans"]}


def _atomic(d: Path, name: str, text: str) -> None:
    """One file, written via tmp + `os.replace`, under the lock sb is already holding.

    `os.replace` is atomic within a directory, so a reader sees the old file or the new one
    and never half of one — which matters even though sb serialises the writers, because a
    plan is a plain file somebody may well `cat` while a job is running. The tmp name is a
    dotfile so that a crash between the two steps cannot leave something the plan glob
    reads as a plan.
    """
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{name}.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, d / name)


def _tomb(d: Path) -> None:
    """Leave a `plans.json` an OLDER plans plugin refuses instead of one it misreads.

    Without this, a plugin from before the split finds no `plans.json` in a store full of
    plans, concludes the repo has none, and writes a fresh single-file store next to them —
    two stores, each invisible to the other. What it finds instead is a file stamped with a
    format it does not speak, which is the one thing a version marker can do.
    """
    if not (d / FILE).exists():
        try:
            d.mkdir(parents=True, exist_ok=True)
            (d / FILE).write_text(_text({
                "format": FORMAT,
                "moved": f"plans are one file each now — see p-<n>.json beside this one"}),
                encoding="utf-8")
        except OSError:
            pass                        # a marker, not a record; never worth a failed verb


def _write(d: Path, doc: dict, seal: dict) -> None:
    """The store back to disk, in whichever shape it is already in. Never the other one.

    Writing does not migrate, for the same reason reading does not: the store is shared,
    the worktrees update one at a time, and a write that changed the shape would take every
    worktree still on the old plugin down as a side effect of a tick. `migrate` is the only
    thing that changes the shape, and somebody types it.

    THE PLAN IS WHAT IS PROTECTED HERE, and only the plan: a plan that was read and is not
    being written back has lost everything it held, and the design says records are kept
    and never erased — cleanup means dropping out of the UI. Two ids for one plan is the
    same loss wearing a different shape and is refused beside it.

    The CHANGELOG is no longer part of that check, and it was until the writing of a plan
    stopped being something an agent did by hand. The rule was that a write whose changelog
    was shorter than the one that was read, or whose existing entries had moved, was a bug
    in a verb — true, and it was also a tax on the thing this plugin now asks for. A plan
    is edited with the tools that edit files: rewriting the file whole is the ORDINARY way
    to change one, no hand-edit is asked to append an entry any more, and a check that
    refused those writes would refuse the interface. The verbs still stamp their own entry
    each time (`_log`), so the record of how a job ran is still made by the things that
    move a plan; what is gone is a rule that could only ever have caught a verb, at the
    cost of standing between an agent and the file.

    What `os.replace` buys is readers, not crashes: a power loss between the rename and
    the blocks reaching disk can still cost the last write, and there is no `fsync` here.
    That is `todo`'s trade taken deliberately, and the cost is one command's worth of
    changelog, not the store.
    """
    here: dict[int, dict] = {}
    for plan in doc["plans"]:
        n = _num(_PLAN_ID, plan.get("id"))
        if n is None:
            raise ValueError(f"this write would have filed a plan with no usable id "
                             f"({plan.get('id')!r}); a plan is addressed by its number")
        if n in here:
            raise ValueError(f"this write would have put two plans under p-{n}, and one "
                             f"of them would be gone; ids are never reused")
        here[n] = plan
    gone = [n for n in seal if n not in here]
    if gone:
        raise ValueError(f"this write would have dropped "
                         f"{', '.join(f'p-{n}' for n in sorted(gone))} and its changelog; "
                         f"plans are kept, never erased")
    (_write_split if _split(d) else _write_one)(d, doc, seal, here)


def _write_one(d: Path, doc: dict, seal: dict, here: dict) -> None:
    """The whole store, one file, format 1 — byte for byte what an older plugin writes.

    A whole-file rewrite for a tick on one step, which is the cost of the shape and the
    reason `migrate` exists. What matters more while a fleet is crossing over is that this
    leaves nothing behind that an older plugin would refuse: the format on disk stays 1,
    and `broken` — which only the split shape can populate — is dropped rather than
    written down as a field nothing else knows about.
    """
    out = {k: v for k, v in doc.items() if k != "broken"}
    out["format"] = LEGACY_FORMAT
    _atomic(d, FILE, _text(out))


def _write_split(d: Path, doc: dict, seal: dict, here: dict) -> None:
    """Only the plans this command actually touched, each to its own file. Nothing else.

    A tick on one step of one plan writes one plan's file and the other nine are not
    opened. Touched is decided by comparing against the text `_read` saw, which is also
    what keeps a plan that failed to load safe: it is not in `doc["plans"]`, so it is never
    a file this writes.
    """
    for n, plan in sorted(here.items()):
        was, body = seal.get(n), _text(plan)
        if was is not None and body == was["raw"]:
            continue                    # untouched by this command; leave the file alone
        _atomic(d, f"p-{n}.json", body)
    meta = _text({"format": FORMAT, "next_plan": _counter(doc.get("next_plan")),
                  "next_step": _counter(doc.get("next_step"))})
    try:
        stale = (d / META).read_text(encoding="utf-8") != meta
    except OSError:
        stale = True
    if stale:
        _atomic(d, META, meta)
    _tomb(d)


def _here(ctx) -> Path:
    """This checkout, resolved. The stable half of a plan's address.

    Resolved because the same worktree is reached by several spellings — a symlinked
    `/tmp`, a relative `cwd`, `/var` against `/private/var` — and a plan filed under one
    of them must still be found from another.
    """
    try:
        return Path(ctx.worktree).resolve()
    except OSError:
        return Path(ctx.worktree)


def _same(stored: Any, here: Path) -> bool:
    """Is a stored checkout this one? False for a record that does not say."""
    if not stored:
        return False
    try:
        return Path(str(stored)).resolve() == here
    except OSError:
        return str(stored) == str(here)


def _workspace(ctx) -> tuple[Optional[str], str]:
    """Which workspace this checkout belongs to, and HOW that was decided. Asked of sb.

    The name has to be the string the store holds — it is what the board groups by and what
    a later PR uses to decide a plan's worktree is gone — and a plugin `Context` carries no
    store handle by design. So this asks sb itself, which D2 already settled as the way a
    plugin reads anything the store owns. Two questions, cheapest first:

    1. The caller's own agent row (`sb inspect <agent> --json`), whose `workspace` is
       exactly the string wanted. This is the normal path: a lead creates the plan.
    2. Otherwise the map from checkout to workspace (`sb workspace list --json`), matched
       on the path. This is the human-at-a-terminal path, and it is second because it is an
       order of magnitude slower to answer.

    A name from anywhere else is not an option. Inventing one from the branch or the
    directory is what this file did before and it was wrong: branches move under a checkout
    that has not, and a plan filed under a name no workspace has reads as a worktree gone.

    So there are two ways to have no name, and they are NOT the same fact:

        none          sb answered, and this checkout is no workspace it knows — a plain
                      clone, or the primary checkout, whose workspaces are bare and share
                      one directory so there is no single right answer to pick.
        unavailable   sb could not be asked or did not answer — not found, non-zero,
                      unparseable, or slower than the budget below.

    Both store `workspace: null`, which is why the second half of this return value exists.
    A record that cannot tell them apart hands PR4 a transient hiccup dressed as a plan
    whose worktree is gone — permanently, since nothing recomputes this. `create` writes
    the answer to `workspace_from`, and the four values are the whole vocabulary:
    `agent`, `workspace-list`, `none`, `unavailable`.

    Called once, by `create`. Nothing else recomputes it, and no verb re-attaches a plan.
    """
    clock = _Budget()
    reached = True
    if ctx.agent:
        row = _ask(ctx, "inspect", ctx.agent, clock=clock)
        reached = row is not None
        name = (row or {}).get("workspace")
        if name:
            return str(name), BY_AGENT
    listed = _ask(ctx, "workspace", "list", clock=clock)
    reached = reached and listed is not None
    here = _here(ctx)
    for w in ((listed or {}).get("workspaces") or ()):
        if not isinstance(w, dict) or not w.get("name"):
            continue
        if not _same(w.get("checkout"), here):
            continue
        # `sb workspace list` also synthesises a row for a checkout it finds in git and
        # nowhere else, and names it after the BRANCH. That is the wrong answer wearing
        # the right shape, and taking it would put the drift this resolver exists to fix
        # straight back. Only a workspace the store knows has a name to file a plan under.
        if set(w.get("sources") or ()) - {"git"}:
            return str(w["name"]), BY_LIST
    return None, (NONE if reached else UNAVAILABLE)


# How long resolving a workspace may cost, in total and for any one question. Measured, not
# guessed: `sb inspect` answers in ~0.4s and `sb workspace list` in ~1.5-2.6s against a
# 260-row store. The budget is shared across both questions rather than per-call, because
# the thing being bounded is `create` — which holds the plugin lock while it waits, so every
# other plans command in the repo waits behind it. An sb that has wedged costs seconds and
# an `unavailable` marker, never a minute of a locked state directory.
BUDGET, PER_ASK = 8.0, 5.0


class _Budget:
    """The wall clock for one resolution, spent across however many questions it asks."""

    def __init__(self) -> None:
        self.until = time.monotonic() + BUDGET

    def left(self) -> float:
        return min(PER_ASK, self.until - time.monotonic())


def _ask(ctx, *argv: str, clock: _Budget) -> Any:
    """One `sb <argv> --json`, parsed, or None if it fails in any way at all.

    Every failure is None rather than an exception: this is a name to label a plan with,
    and a plan that cannot be made because `sb inspect` timed out would be a plugin that
    breaks when the thing it is describing is busy. The caller records that it happened.
    """
    sb = _sb()
    seconds = clock.left()
    if not sb or seconds <= 0:
        return None
    try:
        out = subprocess.run([sb, *argv, "--json"], cwd=str(ctx.worktree),
                             stdin=subprocess.DEVNULL, capture_output=True, text=True,
                             timeout=seconds)
        return json.loads(out.stdout) if out.returncode == 0 and out.stdout else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _sb() -> Optional[str]:
    """Which `sb` to ask — this build's, then whatever is installed.

    `collector.doorbell_sb()`'s reasoning, one directory deeper: a plugin shipped inside a
    checkout is three levels under it, and that checkout's `bin/sb` is the build whose
    store the caller is standing in. Asking PATH first is how a branch's plugin ends up
    interrogating a different build's idea of the world.
    """
    own = Path(__file__).resolve().parents[3] / "bin" / "sb"
    if os.access(own, os.X_OK):
        return str(own)
    return shutil.which("sb")


# -- what is read, every time, and written down nowhere -------------------------


_UNASKED = object()


class _Live:
    """The two things `show` and `list` read off the world instead of out of the file.

    One of these per command. A `list` over twenty plans therefore asks sb ONCE between
    them and spends one `_Budget` doing it — this runs with the plugin lock held, and a
    board that renders plans often must cost one bounded question rather than one per row.

    Every answer here is fail-safe in one direction, and that is most of what the code
    below is for: when sb does not answer, an owner reads `unknown` and a plan reads
    `unknown` — never `dead`, and never `abandoned`. The asymmetry is deliberate. These
    words are read cold by the analysis pass, and a live job that read as abandoned because
    a subprocess timed out leaves exactly the same mark as one that really fell apart.
    """

    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.clock = _Budget()
        self._agents: Any = _UNASKED

    def agents(self) -> Optional[dict]:
        """Every agent sb will name, keyed by name — or None, meaning it would not say.

        `sb status` and not `sb inspect` per owner: one question answers for every step of
        every plan being rendered, where inspect is one subprocess each, is refused across
        the tree boundary anyway, and cannot distinguish "no such agent" from "did not
        answer" once `_ask` has turned both into None.

        None is a THIRD answer and not an empty one. A snapshot that did not arrive says
        nothing about anybody, and the callers below all branch on it before they conclude
        anything about a death or a dormancy.
        """
        if self._agents is _UNASKED:
            snap = _ask(self.ctx, "status", clock=self.clock)
            rows = (snap or {}).get("agents")
            self._agents = ({str(a.get("name")): a for a in rows if isinstance(a, dict)}
                            if isinstance(rows, list) else None)
        return self._agents

    def owner(self, name: Any) -> Optional[str]:
        """A step's owner as the agent itself reads, right now. None when there is no owner.

        Read from the agent and never copied onto the step, which is the design's rule and
        the reason this returns a word rather than writing one: two records both claiming
        to know who is working will disagree, and the one that is wrong is always the copy.

        An owner sb's snapshot does not mention is `unknown` rather than dead. A snapshot is
        scoped to the caller's own tree, so "not in it" is as much a fact about who is
        looking as about the owner — and a step whose owner is merely out of view must not
        send a lead to dispatch a replacement for an agent that is working fine.
        """
        if not name:
            return None
        rows = self.agents()
        if rows is None:
            return UNSEEN
        row = rows.get(str(name))
        if row is None:
            return UNSEEN
        state = str(row.get("state") or "")
        # `gone` as well as `failed`: `gone` is sb saying this agent never reported an end
        # and its pane is not there any more, which is the death a lead needs to see now
        # rather than after the confirmation grace writes `failed` into the row for real.
        if state == "failed" or row.get("gone"):
            return DEAD
        # `display_state` is the store's own reconciliation of the state column against
        # what the pane is doing, and it is part of `sb status`'s contract precisely so
        # that a reader does not re-derive it. Passed through rather than re-spelled.
        word = str(row.get("display_state") or state or "").strip()
        return word or UNSEEN

    def worktree(self, plan: dict) -> str:
        """Is this plan's worktree still there? Decided from the checkout, and nothing else.

        The checkout PATH is the stable handle — PR1 stores it so that this question has
        something to ask about that does not move when a branch does — and a directory that
        is not there is evidence needing nobody's cooperation to read.

        `workspace: null` is NOT evidence and is never read here. PR1 writes that null both
        for a checkout that is no workspace sb knows (`none`) and for an sb that could not
        be asked at all (`unavailable`), and reading the second as a worktree that has gone
        would let one timeout, at one instant, mark a healthy job abandoned for the rest of
        its life — nothing recomputes `workspace_from`, so that verdict would never lift.

        `sb workspace list` is deliberately not asked either, and it is worth saying why,
        since it is the other handle the plan doc names. Its `verdict` for a checkout is
        `store.checkout_verdict`, whose first act is the same existence check made here —
        so the extra information it carries is a workspace RETIRED with its directory still
        standing, which costs one to three seconds under the plans lock on every render and
        buys a second route to a false `gone` if a row is matched wrongly. The directory is
        the fact; a workspace row is a label on it.

        Any OSError that is not FileNotFoundError — an unreadable parent, a mount that is
        not answering — is `unknown`, because "I could not look" and "it is not there" are
        the two answers this whole class exists to keep apart.

        FileNotFoundError is not quite the second of those on its own, and the DIRECTORY
        ABOVE is what finishes the sentence. `os.stat` gives one ENOENT for a worktree that
        was deleted and for a worktree whose parent went away under it — an unmounted
        volume, a `worktrees/` directory that was renamed or moved. The first is a job that
        fell apart; the second is a machine that moved, and a plan on it is not abandoned.
        So the parent is asked too: parent there and checkout not is a deletion, and a
        parent that is also missing is `unknown`. It costs one more stat on the one path
        that was about to return the only verdict here that never lifts.
        """
        checkout = str(plan.get("checkout") or "").strip()
        if not checkout:
            return UNSURE                # a hand-written plan: nothing to go and look for
        try:
            os.stat(checkout)
        except FileNotFoundError:
            return self._deleted(checkout)
        except OSError:
            return UNSURE
        return HERE

    @staticmethod
    def _deleted(checkout: str) -> str:
        """A checkout that is not there: was IT removed, or did the ground move under it?"""
        parent = os.path.dirname(os.path.abspath(checkout))
        try:
            os.stat(parent)
        except OSError:
            # Missing, unreadable, or a mount that will not answer — every one of them is
            # a reason to say nothing rather than to say abandoned.
            return UNSURE
        return GONE

    def condition(self, plan: dict) -> tuple[str, str]:
        """What a plan reads as, and where its worktree is. Derived here, written nowhere.

        The order is the design's. A worktree that has gone decides first, and decides
        between the two words that must not be confused: gone with steps still open is
        ABANDONED and gone with the work done is FINISHED. The sweep deletes a worktree on
        gates that cannot see a plan and are not going to learn to, so if the record does
        not tell those apart afterwards the analysis pass reads every job that fell apart
        as a job that went well — a second, mechanical source of the bias the design's
        known limitations already name.

        Then the work itself: every step ticked or skipped is finished wherever the
        worktree is. An empty plan is NOT finished — `all()` of nothing is true, and a plan
        created a second ago is the last thing that should read as done.

        Then who is there. Every agent on the worktree closed is DORMANT, which is a state
        a plan comes back from: restore one and the next render says live again. Nothing is
        deleted at any point on this ladder — cleanup means dropping out of a UI, and the
        record is plain text that is kept.
        """
        where = self.worktree(plan)
        steps = plan.get("steps") or []
        closed = bool(steps) and all(
            str(s.get("progress") or "") in (DONE, SKIPPED) for s in steps)
        if where == GONE:
            return (FINISHED if closed else ABANDONED), where
        if where == UNSURE:
            return UNSURE, where
        if closed:
            return FINISHED, where
        rows = self.agents()
        if rows is None:
            return UNSURE, where         # cannot tell a dormant worktree from a busy one
        name = plan.get("workspace")
        if not name:
            # A plain clone, or a plan made while sb was unreachable. There is no key to
            # count agents by — an agent row carries a workspace name and not a path — so
            # `dormant` would be a claim about agents nothing here has looked at. The
            # worktree is there and the steps are open: `live` is the reading that keeps it
            # on the board, which is the direction to be wrong in.
            return LIVE, where
        mine = [a for a in rows.values() if a.get("workspace") == name]
        if not mine:
            # NO agent is not the same fact as every agent CLOSED, and `any()` over an
            # empty list would quietly call it one — the same vacuous-quantifier trap the
            # `bool(steps)` guard above closes for a plan with no steps. Nobody was ever
            # closed here: either the plan was made by a human and no agent has been
            # spawned into it yet, or `sb status` is scoped to the caller's own tree and
            # the agents on this worktree belong to another. `_Live.owner` already refuses
            # to read that scoping as a death; this must not read it as a dormancy.
            return LIVE, where
        if any(str(a.get("state") or "") not in CLOSED for a in mine):
            return LIVE, where
        return DORMANT, where


def _viewed(shown: dict, live: _Live) -> dict:
    """A resolved plan with what was read live added to the COPY, and only to the copy.

    This is where "never stored" is actually kept, so it is worth being explicit about the
    one trap in it: `_resolve` hands BACK THE STORED DICT for a step that owns its own
    words, so annotating a step in place would write an owner's status into the plan's file on
    the next command that happens to write. Every step is copied again here, and there is
    no path from anything below to `_write` at all.
    """
    steps = [dict(s, owner_status=live.owner(s.get("owner")))
             for s in (shown.get("steps") or ())]
    condition, where = live.condition(shown)
    return dict(shown, steps=steps, condition=condition, worktree=where)


# -- rendering and lookup ------------------------------------------------------


def _find(doc: dict, given: str) -> Optional[dict]:
    n = _num(_PLAN_ID, given)
    return next((p for p in doc["plans"] if _num(_PLAN_ID, p.get("id")) == n), None) \
        if n else None


def _locate(doc: dict, given: str) -> tuple[Optional[dict], Optional[dict]]:
    """The step this id names, and the plan holding it. Two spellings, one function.

    QUALIFIED — `p-16/step-3` — names the plan on the front of the step, separated by a
    slash, and is the spelling that always works. It is the answer to step numbers no
    longer being unique across the store: two plans on a worktree both have a `step-1` now,
    and `p-16/step-1` says which.

    BARE — `step-3`, `s-3`, `3` — resolves when exactly ONE plan holds that number, and
    otherwise resolves to nothing so that `_no_step` can refuse naming the candidates. That
    keeps the ergonomics globality was for (a worktree almost always holds one plan) without
    keeping the constraint that made two plans share a counter.

    Returns `(None, None)` for every miss, including an ambiguous bare id and a qualifier
    naming no plan; every caller refuses through `_no_step`, which re-reads the id and says
    which kind of miss it was.
    """
    plan_id, sep, step_id = str(given or "").rpartition("/")
    if sep:
        plan = _find(doc, plan_id)
        return (plan, _in_plan(plan, step_id)) if plan is not None else (None, None)
    n = _num(_STEP_ID, given)
    if not n:
        return None, None
    hits = [(p, st) for p in doc["plans"] for st in (p.get("steps") or ())
            if _num(_STEP_ID, st.get("id")) == n]
    return hits[0] if len(hits) == 1 else (None, None)


def _in_plan(plan: Optional[dict], given: Any) -> Optional[dict]:
    """One plan's step by number. The lookup every id comparison in this file is made of."""
    n = _num(_STEP_ID, given)
    return next((st for st in (plan or {}).get("steps") or ()
                 if n and _num(_STEP_ID, st.get("id")) == n), None)


def _holders(doc: dict, n: int) -> list[dict]:
    """The plans holding a step with this number. What an ambiguous bare id refuses with."""
    return [p for p in doc["plans"]
            if any(_num(_STEP_ID, st.get("id")) == n for st in (p.get("steps") or ()))]


def _num(pattern: re.Pattern, given: Any) -> Optional[int]:
    """The number in an id, or None. Zero is not a number an id has.

    Ids are minted from 1, so `p-0` only ever arrives by hand — and everything here reads
    a number for truth (`if n`), which would quietly make a `p-0` unfindable rather than
    refused. Saying no once, here, is what makes that impossible everywhere else.
    """
    m = pattern.match(str(given or "").strip())
    n = int(m.group(1)) if m else None
    return n if n else None


def _high(pattern: re.Pattern, ids) -> int:
    return max((n for n in (_num(pattern, i) for i in ids) if n), default=0)


def _count(steps: list) -> str:
    return "empty" if not steps else f"{len(steps)} step{'s' if len(steps) > 1 else ''}"


def _where(p: dict) -> str:
    """A plan's workspace, or which kind of no-workspace it is, said rather than blank.

    An em dash here would read as "not filled in yet". A plan may be on a checkout that is
    no workspace sb knows — a plain clone, the primary checkout whose workspaces are bare
    and share one directory — and that is a real answer, not a gap. The other null is sb
    having been unreachable when the plan was made, and it renders differently because
    nothing about the job is being described: the record simply does not know.
    """
    if p.get("workspace"):
        return _flat(p["workspace"])
    return "(unresolved)" if p.get("workspace_from") == UNAVAILABLE else "(no workspace)"


def _line(p: dict, *, workspace: bool) -> str:
    """One plan as `list` draws it. Handed a RESOLVED plan, like everything else here.

    The workspace goes through `_col`, which is `_key_col`'s two-space floor and is here
    for the bug that function was written for: `f"{...:<24}"` pads a short value and does
    nothing at all to a long one, so a workspace named past the column glued itself to the
    title and the two read as one word.

    `!` in front is the THIRD DOOR — a plan missing a display name or a dep, marked where
    a lead scans for what to do next. One character, because this is a table: what is
    wrong with it is `show`'s to say and the board's to draw in red.
    """
    where = _col(_where(p), 24) if workspace else ""
    # The condition is a column on the listing and not a footnote: what a lead scanning
    # `list` wants first is which of these plans anybody is still on.
    cond = f"{str(p.get('condition') or ''):<11}" if p.get("condition") else ""
    short, bad = _defective(p)
    return (f"{'!' if short or bad else ' '}{p['id']:<6}"
            f"{_count(p.get('steps') or []):<10}{cond}{where}"
            f"{_flat(p.get('display') or p.get('title') or '(untitled)')}")


def _full(p: dict) -> str:
    """A plan as a lead reads it: what it is, its steps and their edges, then the story.

    Handed a RESOLVED plan — `_shown` — so that a named step renders as the words in the
    library rather than as a null. Nothing in here reaches for the catalogue itself: the
    resolution happens once, at the verb, and this stays a function of what it was given.

    The same is true of the condition and the owner statuses, which is why both are drawn
    only when they are there: `show` and `list` derive them (`_viewed`), and the verbs that
    WRITE do not — a tick should not also pay a subprocess to say who is alive, and `show`
    is one command away.
    """
    lines = [f"{p['id']}  {_flat(p.get('title') or '(untitled)')}"]
    if p.get("display"):
        # The title is what the job is and this is what the BOARD draws instead of it, so
        # an author reading a plan back can see the header a glance will actually get.
        lines.append(f"  board       {_flat(p['display'])}")
    lines += [f"  workspace   {_where(p)}",
              f"  checkout    {_flat(p.get('checkout') or '—')}"]
    if p.get("condition"):
        lines.append(f"  condition   {_condition(p)}")
    lines.append(f"  created     {_when(p.get('created_at'))} "
                 f"by {_flat(p.get('created_by') or '—')}")
    steps = p.get("steps") or []
    lines.append("")
    lines.extend([f"  {s}" for s in (_step_lines(steps) or ["(no steps yet)"])])
    if p.get("notes"):
        lines.append("")
        lines.append("  notes")
        lines.extend(f"    {_flat(n.get('text'))}  ({_flat(n.get('by'))}, "
                     f"{_when(n.get('at'))})"
                     for n in p["notes"])
    lines.append("")
    lines.append("  changelog")
    lines.extend(f"    {_entry(e)}" for e in (p.get("changelog") or ()))
    return "\n".join(lines)


# Every key the template below draws BY NAME, which is the one thing it has to know to
# draw the rest: what is left over is a field this file has never heard of, and the last
# line of a step is where one goes. `owner_status`, `condition` and `command` are in here
# for the same reason the stored fields are — they arrive on the rendered copy (`_viewed`,
# `_resolve`), are drawn above, and a renderer calling them unknown prints them twice.
_DRAWN = frozenset({"id", "name", "display", "def", "obliged_by", "progress", "why",
                    "gate", "output", "owner", "owner_status", "tries", "notes", "deps",
                    "checkpoints", "command", "root", "anchor"})


def _step_lines(steps: list) -> list[str]:
    """One line per step, plus a line each for what hangs off it.

    The reason, the refs and the notes are written out rather than counted. A step line
    saying `[2 checkpoints]` tells a lead there is something to go and look for and not
    where it is, and a skipped step whose reason is twenty lines down in the changelog is
    the absence this design exists to avoid — `show` is the place a plan is read in full.
    """
    out = []
    for s in steps:
        # Nine, because an id is `step-<n>` now and `s-<n>` on a plan made before that:
        # the column has to hold the longer spelling or the progress beside it runs into
        # it, which is a rendering nobody can scan.
        bits = [f"{_flat(s.get('id', '?')):<9}{_flat(s.get('progress', '?')):<10}"
                f"{_flat(s.get('name') or '')}"]
        if s.get("display"):
            # The label the board draws for this step, beside the sentence it stands for —
            # the two are authored together and a display nobody ever sees written next to
            # its name is a display nobody notices has gone stale.
            bits.append(f"[board {_flat(s['display'])}]")
        if _defkey(s):
            # The link is shown, not just what it resolves to: a lead deciding whether to
            # edit a definition or write a variant has to be able to see which steps are
            # links, and a resolved name looks exactly like a step somebody typed.
            bits.append(f"[{_flat(_defkey(s))}]")
        if s.get("obliged_by"):
            bits.append(f"obliged by {_flat(s['obliged_by'])}")
        if s.get("gate"):
            # The word on the line and the sentence below it. A lead scanning a plan needs
            # to see WHICH steps end in a human without reading every exit condition, and
            # whoever is about to work the step needs the sentence itself — so both, rather
            # than a marker that sends somebody looking or a sentence that hides in the run
            # of a long line.
            bits.append("gate")
        if s.get("owner"):
            # The two things the design says a step shows, side by side: its progress —
            # above, set by a lead or the owner — and its owner's status, read off the
            # agent at this instant and set on nothing. A dead owner is on this line the
            # moment somebody looks, which is how the lead learns of a death at all.
            status = s.get("owner_status")
            bits.append(f"({_flat(s['owner'])}"
                        + (f" — {_flat(status)})" if status else ")"))
        if s.get("deps"):
            # Edges the lead interprets: what this one waits for, never a wait anything runs.
            bits.append(f"after {', '.join(_flat(d) for d in s['deps'])}")
        elif s.get("root"):
            # The one thing said about a step that has NO edge, and only where the record
            # says the absence is meant: a reader counting starts should see which of them
            # were authored as starts rather than diff the plan against a warning.
            bits.append("parallel start")
        if _counter(s.get("tries")) > 1:
            bits.append(f"try {_flat(s['tries'])}")
        out.append("  ".join(bits))
        if s.get("why"):
            out.append(f"    — {_flat(s['why'])}")
        if s.get("gate"):
            # Said where the gate is read, which since the guide stopped naming gates is
            # the ONLY place it is said: the two things somebody meeting one has to know
            # are what they are being asked and that there is nothing here to type when they
            # answers. A step whose owner shows `blocked` on
            # the line above is this gate being reached, which is the only signal there is.
            out.append(f"    gate  {_flat(s['gate'])}"
                       f" — its owner blocks; answering the owner clears it, and no verb "
                       f"here does")
        if _some(s.get("output")):
            # The other view of the same record. A field that only ever appeared on a pull
            # request comment would be a field nobody proofreads before it is posted, and
            # what this one carries is the text a human approved — so it is printed here
            # too, one line per line, SPLIT FIRST so that no line of it can forge a step
            # row the way the whole thing could if it were pasted in unbroken.
            out.extend(f"    out   {line}" for line in _lines(s["output"]))
        if s.get("command"):
            # The command the definition carries, written out where the step is read. It is
            # printed and never run: nothing in this plugin executes a step, and a plan that
            # fired commands would be the evaluator this design does not have. The
            # placeholders in it are the owner's to fill in.
            out.append(f"    cmd   {_flat(s['command'])}")
        out.extend(f"    ref   {_flat(c.get('ref'))}" for c in (s.get("checkpoints") or ()))
        out.extend(f"    note  {_flat(n.get('text'))}  ({_flat(n.get('by'))}, "
                   f"{_when(n.get('at'))})"
                   for n in (s.get("notes") or ()))
        # EVERYTHING ELSE THE STEP CARRIES, last, one line each. This template knows every
        # field above by name, so before this a field nobody here had heard of rendered in
        # `--json` and in `--markdown` and was silently invisible in the terminal — while
        # the top of this file promised the opposite, that such a field is a feature and
        # not corruption. It is the promise that was true; this is the renderer catching
        # up, in the same falls-back-rather-than-fails spirit `_markdown` is walked for.
        #
        # Through `_flat` like every other value drawn here, key included, so an invented
        # field is one line UNDER its step and can no more forge a row beside it than a
        # gate or a name can. A non-scalar is left to `--json`: a list has no place under
        # a step line, and this door exists to fall back rather than to raise on one.
        # The key IS the label, padded to the width the labels above are drawn at and
        # never narrower than the two spaces that separate it from its value: a field
        # called `reviewed_by` would otherwise run straight into what it says.
        out.extend(f"    {_flat(k) + '  ':<6}{_flat(v)}" for k, v in s.items()
                   if k not in _DRAWN and _scalar(v) and _some(v))
    return out


# Resolved onto the view for the code to read and for NO RENDERING TO PRINT. `anchor` is
# the only one: a step's name, display and command are resolved for a reader, and this is
# resolved for `_wrong`, which has to know where a step runs to tell an obligation left out
# of the order from one the anchors ordered the other way, and which is handed a resolved
# plan and never the catalogue.
#
# Kept out of both renderings by two different means, because they are two different
# mechanisms. The terminal draws only what it does not already know how to draw, so this
# joins `_DRAWN`. The markdown is WALKED and knows no field names at all — which is the
# whole point of it — so nothing in that renderer could be taught to skip a key without
# taking that property away; what happens instead is that the field is dropped from the
# copy being dumped (`_dumped`), one call above it. `--json` carries it either way, since
# that rendering is the record and a machine reader is who this field is for.
_MACHINERY = frozenset({"anchor"})


def _dumped(shown: dict) -> dict:
    """A resolved plan with the machinery taken back out, for the rendering a HUMAN reads.

    `show --markdown` is what `create-pr` posts onto the pull request, so what is in it is
    what whoever turns up reads. `anchor: pr` under a step means nothing to that reader and
    is not a fact about the job — it is how this file decided where to put the step, which
    it did weeks earlier. Dropped from the copy rather than skipped by the renderer: see
    `_MACHINERY`. A copy, so `data` is untouched and `--json` still means what it meant.
    """
    return dict(shown, steps=[{k: v for k, v in s.items() if k not in _MACHINERY}
                              for s in (shown.get("steps") or ())])


# -- the plan as markdown ------------------------------------------------------
#
# WALKED, NOT TEMPLATED. `_full` above is the terminal rendering and knows every field by
# name. This one deliberately does not, because of where it goes: a pull request comment,
# posted by one step definition and rewritten by another, read by whoever turns up. A
# rendering with the schema written into it stops being true the week a field is added and
# raises the week one is dropped — in front of somebody's merge, from a step that is only
# supposed to be reporting. So this walks the record instead: a new field appears here on
# its own, a removed one vanishes, and neither costs an edit to this function.
#
# What it does know about the schema is three things, and every one falls back rather than
# fails: the keys that might name the plan in its heading (`_HEADS`), the keys whose value
# is prose to be dumped rather than flattened (`_BLOCK`), and that a key called `at` or
# ending `_at` holding an integer is a timestamp. Everything else is shape — scalar,
# list, dict — and the shape decides the rendering:
#
#   scalar fields          one `field | value` table under the heading
#   list of flat dicts     a table, columns being the union of the keys actually used
#   anything else          nested bullets, each item labelled by its first scalar field
#
# IDS ARE SPELT OUT HERE and nowhere else: a value that IS an id — `p-1`, `s-3` — renders
# as `plan-1`, `step-3`. That is a rule about VALUES and not about the schema, which is why
# it can live in a renderer that refuses to know one: it needs no list of which keys hold
# ids, so a plan id, a step id, a `deps` entry, an `obliged_by` and whatever field a later
# author puts an id in all come out readable without this function being told they exist.
# Storage is untouched — `p-<n>` and `p-<n>.json` are what is written — and `_PLAN_ID` and
# `_STEP_ID` read the long spelling back, so an id copied out of this rendering and typed
# into a command resolves.
#
# ONE PLAN. It is handed the single resolved plan dict `show` already has and has no path
# to the store, so there is nothing here that could widen into every plan in the repo.

_HEADS = ("display", "title")            # what names the plan, best first; both optional
_BLOCK = ("output",)                     # keys whose value is prose, dumped rather than
#                                          flattened — the third schema fact, and it falls
#                                          back like the other two: a `_BLOCK` key holding
#                                          anything but a string takes the ordinary path.
#
# Every line of a dump is BLOCKQUOTED, which is what keeps the forged-row property the rest
# of this file holds by escaping: no line inside a quote can start a step row or a markdown
# table row, however it is spelled. It does not stop a `#` in the text becoming a heading
# INSIDE its own quote, and that is accepted — this is the step's own text, deliberately
# dumped, and it is visibly quoted while it does it.

# The short spelling of an id, as a WHOLE value. See `_readable`.
_LONG = re.compile(r"^(p|s)-(\d+)$", re.IGNORECASE)


def _markdown(p: dict) -> str:
    """One plan as markdown: a heading, its scalar fields, then a section per collection."""
    used = next((k for k in _HEADS if _some(p.get(k))), None)
    head = " — ".join(x for x in (_cell("id", p.get("id")) if _some(p.get("id")) else "",
                                  _cell(used, p[used]) if used else "") if x)
    lines = ["# " + (head or "plan")]
    skip = {"id"} | ({used} if used else set())
    rows = {k: v for k, v in p.items() if k not in skip and _scalar(v) and _some(v)}
    if rows:
        lines += ["", "| field | value |", "| --- | --- |"]
        lines += [f"| {_title(k)} | {_cell(k, v)} |" for k, v in rows.items()]
    for k, v in p.items():
        if k in skip or _scalar(v) or not _some(v):
            continue
        lines += ["", f"## {_title(k)}", ""]
        lines += _table(v) if _tabular(v) else _bullets(v)
    return "\n".join(lines)


def _scalar(v) -> bool:
    """Is this a value rather than a collection? The only type question asked here."""
    return not isinstance(v, (dict, list, tuple))


def _some(v) -> bool:
    """Is there anything here to render at all?

    A null, an empty string and an empty list are the same absence, and all three are
    dropped rather than drawn as an em dash: this rendering is read by somebody who has
    never seen the schema, and a row saying `gate —` invites them to wonder what a gate is
    and why this one is missing. `False` and `0` are values and survive.
    """
    if isinstance(v, (dict, list, tuple)):
        return bool(v)
    return v is not None and str(v) != ""


def _inline(v) -> bool:
    """Does this fit on the end of its own bullet, or does it need bullets of its own?"""
    if _scalar(v):
        return True
    return all(_scalar(x) for x in (v.values() if isinstance(v, dict) else v))


def _tabular(v) -> bool:
    """A list of dicts with nothing nested in any of them — the one shape a table suits.

    Asked of the values that are actually there, so a step carrying an empty `notes` list
    is still flat: an absent collection is not a nested one.
    """
    return (isinstance(v, list) and bool(v) and all(isinstance(i, dict) for i in v)
            # A block goes in bullets or it goes nowhere: a table cell is one line, so a
            # plan whose steps happened to be flat could otherwise push a whole approved
            # contract into one, which is the shape this rendering exists to avoid.
            and not any(isinstance(i.get(k), str) and _some(i.get(k))
                        for i in v for k in _BLOCK)
            and all(_scalar(x) or not _some(x) for i in v for x in i.values()))


def _title(key: str) -> str:
    """A key as a human word. Nothing is renamed — underscores are just not read aloud."""
    return _flat(key).replace("_", " ")


def _cell(key: str, v) -> str:
    """One value as one line of markdown text.

    Through `_flat` like every other renderer in this file, so a newline somebody stored in
    a field shows as the `\\n` it is rather than as the extra table row it was aiming to
    be — the forged-row property this file holds everywhere else holds here too, and a
    markdown table is exactly the kind of thing a row-forger is written for. The pipe is
    escaped for the same reason and only for markdown's sake.
    """
    if isinstance(v, (list, tuple)):
        return ", ".join(_cell(key, x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{_title(k)}: {_cell(k, x)}" for k, x in v.items() if _some(x))
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int) and (key == "at" or key.endswith("_at")):
        return _when(v)
    return _readable(_flat(v)).replace("|", "\\|")


def _readable(text: str) -> str:
    """`p-1` → `plan-1`, `s-3` → `step-3`. A whole value or nothing.

    Anchored, so it changes an id and never a sentence that contains one: a changelog detail
    reading `3 steps (s-1, s-2, s-3)` is history quoted verbatim and is left exactly as its
    author wrote it, which is the same rule the rest of this file follows about the record.
    Applied after `_flat`, so nothing here can reintroduce a character `_flat` took out.
    """
    return _LONG.sub(lambda m: f"{'plan' if m.group(1).lower() == 'p' else 'step'}-"
                               f"{m.group(2)}", text)


def _table(items: list) -> list[str]:
    """A list of flat dicts as a table: the columns are the keys that carry something.

    The union across every row and in the order they are first met, so a field only some
    rows have still gets a column and a field nothing fills gets none. Nothing is dropped
    for width — a table narrow enough to read but missing a column is the failure mode
    this rendering exists to avoid.
    """
    cols: list = []
    for i in items:
        cols += [k for k in i
                 if k not in cols and any(_some(x.get(k)) for x in items)]
    if not cols:
        return []
    out = ["| " + " | ".join(_title(c) for c in cols) + " |",
           "| " + " | ".join("---" for _ in cols) + " |"]
    for i in items:
        out.append("| " + " | ".join(
            _cell(c, i.get(c)) if _some(i.get(c)) else "" for c in cols) + " |")
    return out


def _bullets(value, depth: int = 0) -> list[str]:
    """Anything else, as nested bullets. Recursive, so depth is a property of the record.

    A dict item is labelled by its FIRST scalar field rather than by a field named here —
    which is `id` for a step, and stays sensible for a record this file has never seen,
    since whatever an author put first is what they thought identified it.
    """
    pad = "  " * depth
    out: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if not _some(v):
                continue
            if k in _BLOCK and isinstance(v, str):
                # The label, then the text itself, quoted line by line. `_cell` would give
                # the whole thing back as one line with the newlines spelled `\n`, which is
                # right for every other field here and is exactly wrong for the one field
                # whose reason to exist is arriving on a pull request as prose.
                out.append(f"{pad}- {_title(k)}")
                out.extend(f"{pad}  > {line}" for line in _lines(v))
            elif _inline(v):
                out.append(f"{pad}- {_title(k)}: {_cell(k, v)}")
            else:
                out.append(f"{pad}- {_title(k)}")
                out.extend(_bullets(v, depth + 1))
        return out
    for item in value:
        if _scalar(item):
            out.append(f"{pad}- {_cell('', item)}")
        elif isinstance(item, dict):
            keys = [k for k in item if _some(item[k])]
            # A block is never the label, even on a record whose only scalar it is: a label
            # is one line and a block is not, so a dump reaching here would be the forged
            # row the blockquote below is what stops.
            lead = next((k for k in keys
                         if _scalar(item[k]) and not (k in _BLOCK
                                                      and isinstance(item[k], str))), None)
            out.append(f"{pad}- **{_cell(lead, item[lead])}**" if lead else f"{pad}-")
            out.extend(_bullets({k: item[k] for k in keys if k != lead}, depth + 1))
        else:
            out.extend(_bullets(item, depth))
    return out


def _condition(p: dict) -> str:
    """A plan's condition with the sentence that says what it is claiming.

    The word alone is not enough for the two that matter. `abandoned` is a verdict about a
    job and has to say what it was read off; `unknown` has to say, plainly, that nothing is
    being claimed at all — an agent that reads `unknown` as `dead` is exactly the mistake
    this whole file is arranged to prevent.
    """
    word = str(p.get("condition") or "")
    if word == UNSURE:
        say = ("its worktree could not be checked, which is not the same as gone"
               if p.get("worktree") == UNSURE
               else "sb did not answer, which is not the same as nobody working here")
    else:
        say = {LIVE: "somebody is working on this worktree",
               DORMANT: "every agent on this worktree is closed; restoring one brings "
                        "it back",
               FINISHED: "every step is ticked or skipped",
               ABANDONED: "its worktree is gone with steps still open"}.get(word, "")
    return f"{word} — {say}" if say else word


def _changed(plan: dict, step: dict, lib: dict, nxt: list = ()) -> Result:
    """What a step verb hands back: the plan it was in, and the step as it now stands.

    The step alone, not the whole plan — a tick that printed the entire plan back would
    bury the one line that changed, and `show` is a command away. `data` names the plan
    anyway, because a machine reader given only a step has lost which plan it belongs to
    and there is no verb that maps one back to the other. Resolved, like every other read:
    a tick on a named step should say what it ticked and not print a null.

    `nxt` is what this move released (`_next`), printed with its instructions IN FULL —
    the one place a definition's `about` reaches the agent that is about to need it. Long,
    and deliberately: it is a page an agent reads once at the moment it starts a step, not
    a field on a listing, which is exactly why `show` does not carry it for every step.
    """
    shown = _resolve(step, lib)
    lines = [f"{plan['id']}  {_flat(plan.get('title') or '(untitled)')}"]
    lines.extend(f"  {ln}" for ln in _step_lines([shown]))
    ready = [_resolve(s, lib) for s in nxt]
    if ready:
        lines.extend(["", "next — this move unblocked:"])
        for s, raw in zip(ready, nxt):
            lines.extend(f"  {ln}" for ln in _step_lines([s]))
            lines.extend(f"  {ln}" for ln in _how(raw, lib))
    # THE SECOND DOOR: recomputed over the whole plan after the write, appended, and never
    # a refusal. A step verb that refused a plan for a rendering rule would be a `tick`
    # that does not land, which is worse than the rendering it was protecting.
    defects = _defects(_shown(plan, lib))
    data: dict = {"plan": plan["id"], "step": shown}
    if ready:
        data["next"] = [dict(s, about=_instructions(r, lib)) for s, r in zip(ready, nxt)]
    if defects:
        lines.extend(["", *defects])
        data["incomplete"] = defects
    return Result(human="\n".join(lines), data=data)


def _instructions(step: dict, lib: dict) -> Optional[str]:
    """HOW this step is done, in the words of whoever wrote it down. Never a copy.

    A named step's is its definition's `about`, resolved live out of the library exactly as
    its name and its command are — the library owns how a named step is done, and a copy of
    it on the step would be the link quietly turned into a snapshot. This is the field
    `_resolve` deliberately does NOT merge onto a step: it is a page long, `show` draws a
    plan as lines, and a page under every step would bury the plan it belongs to.

    A step that owns its words may carry an `about` of its own, written into the file like
    every other field this plugin has never heard of. A lead that writes the how-to for a
    one-off step gets it surfaced by the same door the library steps use.
    """
    key = _defkey(step)
    spec = (lib.get(key) or {}) if key else step
    return " ".join(str(spec.get("about") or "").split()) or None


def _how(step: dict, lib: dict) -> list[str]:
    """`_instructions` as indented, wrapped lines under the step it belongs to."""
    text = _instructions(step, lib)
    return [f"  {ln}" for ln in textwrap.wrap(_flat(text), 84)] if text else []


def _added(plan: dict, steps: list, lib: dict) -> Result:
    """`_changed` for the verb that adds several at once. `steps`, plural, and on purpose.

    Naming one definition can land three steps — a composite, plus what it obliges — so a
    caller handed a single `step` would be told about one of them and left to discover the
    rest. The key is different from `_changed`'s for the same reason: a reader that gets
    `steps` knows it is looking at everything the command did.
    """
    shown = [_resolve(s, lib) for s in steps]
    lines = [f"{plan['id']}  {_flat(plan.get('title') or '(untitled)')}"]
    lines.extend(f"  {ln}" for ln in _step_lines(shown))
    defects = _defects(_shown(plan, lib))       # the second door; see `_changed`
    data: dict = {"plan": plan["id"], "steps": shown}
    if defects:
        lines.extend(["", *defects])
        data["incomplete"] = defects
    return Result(human="\n".join(lines), data=data)


def _key_col(key: str) -> str:
    """A catalogue key in its column. `_col`, at the width the library listing uses."""
    return _col(_flat(key), 16)


def _col(text: str, n: int) -> str:
    """A value in its column, with a gap even when the value overruns the column.

    `f"{text:<16}"` pads a short value and does nothing at all to a long one, which glued
    `merge-human-review` to its name in the library listing and a long workspace name to
    its plan's title in `list --all`. Two spaces is the floor, the column is the aim.
    """
    return f"{text:<{n}}" if len(text) < n else f"{text}  "


def _def_lines(key: str, spec: dict, lib: dict, *, full: bool) -> str:
    """One definition as the library renders it: its name, and what naming it does."""
    lines = [f"{_key_col(key)}"
             f"{_flat(str(spec.get('name') or '').strip() or '(unnamed)')}"]
    display = str(spec.get("display") or "").strip()
    if display:
        # What the board draws for this step, shown so an author can see the short label the
        # long name above collapses to rather than having to open a board to find out.
        lines.append(f"    board       {_flat(display)}")
    anchor = str(spec.get("anchor") or "").strip()
    if anchor:
        # WHERE it runs, beside what it is, because that is the half of a definition a
        # lead used to have to work out by reading the prose and then fix by hand.
        lines.append(f"    runs        {_flat(anchor)}")
    parts = _names(key, spec, "steps")
    if parts:
        lines.append(f"    composes    {', '.join(_flat(x) for x in parts)}")
    for ob in _obliges(lib, key):
        lines.append(f"    obliges     {_flat(ob)} — added with it, skippable with a reason, "
                     f"never omitted")
    command = str(spec.get("command") or "").strip()
    if full and command:
        # Only with a name, beside the prose, because that is where a definition is READ in
        # full — the listing is for choosing one and a command in it would be a wall of argv
        # between two names. Where the command has to be to hand is on the step itself, and
        # `_resolve` puts it there.
        lines.append(f"    command     {_flat(command)}")
    if full:
        lines.extend(_about(spec))
    return "\n".join(lines)


def _template_lines(key: str, spec: dict) -> str:
    lines = [f"{_key_col(key)}"
             f"{_flat(str(spec.get('title') or '').strip() or '(untitled)')}",
             f"    {_count(spec.get('steps') or [])}"]
    lines.extend(_about(spec))
    return "\n".join(lines)


def _about(spec: dict) -> list[str]:
    """A definition's or a template's prose, wrapped. Written in the file, not in this one.

    Wrapped here rather than kept short in the catalogue, because a definition is where the
    thinking behind a step lives and a rendering that punished a paragraph would push that
    thinking back out into agents' heads — which is what the library exists to stop.
    """
    text = _flat(" ".join(str(spec.get("about") or "").split()))
    return [f"    {line}" for line in textwrap.wrap(text, 84)] if text else []


def _no_def(lib: dict, name: str) -> Result:
    """No such definition. Both halves escaped: `library` takes an uncapped name, and the
    keys are FILENAMES — a POSIX filename may legally hold a tab or a newline."""
    said = _flat(name)
    why = (f"no step definition '{said}' — the library holds "
           f"{', '.join(_flat(k) for k in lib)}" if lib
           else f"no step definition '{said}' — the library is empty, so every step is "
                f"invented on the fly")
    return Result(ok=False, human=why, data={"error": why, "name": name})


def _clip(text: str, n: int = 60) -> str:
    """A preview of some text for the changelog, so an entry says what it was about.

    Clipped rather than whole: the text itself is on the step, and a changelog that
    duplicated every note in full would be the notes twice with one copy going stale.
    """
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _entry(e: dict) -> str:
    bits = [_when(e.get("at")), _flat(e.get("by") or "—"), _flat(e.get("action") or "—")]
    line = "  ".join(bits)
    if e.get("detail"):
        line += f"  {_flat(e['detail'])}"
    # The reason last and set off, because it is the part written for somebody reading the
    # job cold months later, and the only part no command could have supplied for itself.
    return line + (f"  — {_flat(e['reason'])}" if e.get("reason") else "")


def _when(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "—"


def _no_such(doc: dict, given: str) -> str:
    said = _flat(given)                 # see `_missing`: an id is never vetted text
    if _num(_PLAN_ID, given) is None:
        return f"'{said}' is not a plan id — they look like p-1"
    # Named rather than merely denied: ids are never reused, so "there is no p-9 yet" and
    # "p-9 was there and is gone" are different things, and only the first can happen.
    # Counting the files that did not load as well: "the highest is p-8" while a broken
    # `p-9.json` sits in the directory is the plugin telling a human the opposite of what
    # is on their disk, and p-9 is exactly the plan they are asking about.
    high = _high(_PLAN_ID, [p.get("id") for p in doc["plans"]]
                 + [b["id"] for b in doc.get("broken") or ()])
    return (f"no plan {said} — none has been made yet" if not high
            else f"no plan {said} — the highest is p-{high}")
