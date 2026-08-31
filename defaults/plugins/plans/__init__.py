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

    plan   {"id": "p-1", "kind": "plan", "workspace": "task-guardrails-build",
            "workspace_from": "agent", "checkout": "/…/…", "title": "…", "display": "…",
            "next_step": 4, "steps": [...], "changelog": [...], "notes": [...],
            "change": {...}, "created_by": "lead", "created_at": 1754570000}

    step   {"id": "step-1", "name": "…", "display": null, "def": null, "obliged_by": null,
            "progress": "open", "why": null, "gate": null, "output": null, "owner": null,
            "tries": 1, "notes": [], "deps": [], "root": false, "checkpoints": []}

    record {"id": "p-2", "kind": "record", "workspace": "…", "checkout": "…", "title": "…",
            "display": "…", "changelog": [...], "notes": [...], "change": {...},
            "created_by": "w1", "created_at": …}

TWO DOCUMENTS, ONE STORE. A `plan` is the hand-shaped step graph this file has always held;
a `record` is a change record with no plan — the landing facts a DIRECT change accumulates.
Both share the `p-<n>` ids, the file-per-plan storage, the locking, the crash-safety and the
migration. A record is no longer stepless: it is born with a FIXED execution+landing skeleton
(`_skeleton`) so a direct change is legible on the board and its PR — what a record does not
have is a hand-shaped graph, only the fixed one, and the step renderers read both alike.
`kind` tells them apart, and its ABSENCE means `plan` — which is the whole of backward
compatibility for the field: every document written before Phase 3 is a plan and reads as
one without being rewritten, and a record written before the skeleton simply has no steps to
draw.

    change {"path": "direct"|"shaped", "phase": "shaping"|…|null, "request": …, "contract": …,
            "cause": …, "solution": …, "scope"?: …, "verification": {...}, "review": {...},
            "limitations"?: …, "baseline"?: …,
            "human_checks": […]|"none"|null, "pr": {number, head},
            "approval": {plan_revision, contract_digest, by, at},
            "landing": {head, by, at, outcome, cleanup}, "handoff"?: {from, to, at}}

THE CHANGE RECORD is a document-level object — never a step field, so the step schema above
is untouched — carrying the landing lifecycle every change has whether or not a plan exists:
the human request or approved contract, the combined change approval, the verification
evidence and the commit it covers, the independent review and its target, the human-only
checks, the PR head, the human's landing approval and the head it covers, and the outcome. A
SHAPED change (a plan) is born with one at `create`; a DIRECT change gets one from `record`,
only when landing metadata is needed. The identity-bound fields name the commit or head they
cover — `approval` binds the plan REVISION and contract DIGEST it was approved against — so
landing compares an identity once rather than rerunning the work, and implementation is
presented as sanctioned only once the approval is recorded (`_change_defects`). `handoff` is
optional and present only when a fresh main took the work over. Born sparse and rendered only
once it holds a landing fact, so a fresh plan reads as it did before the record existed.

`progress` is an OPEN VOCABULARY, exactly as `todo`'s `state` is: `open` is what `create`
writes and `done`/`skipped` are what the lifecycle verbs will, but nothing here is an enum
and a lead that wants `progress: waiting on Andrew` gets it without a release. The design
says the agent is the interpreter and a step's fields are OPEN, so a step carrying a
field this file has never heard of is a feature and not corruption — `_step()` fills in the
fields the design names and leaves everything else alone, and EVERY RENDERING SHOWS IT:
`--json` and `--markdown` because neither knows a schema, and the terminal view because
`_step_lines` draws what it has no name for on a line of its own under the step — a scalar
one, that being what a line holds; a list or an object is left to `--json`, which is the
shape that can carry one. A promise kept in two renderings out of three was one the third
made a liar of.

ONE FIELD IS SHAPED, AND IT IS ADVISORY. `strategy` — a step's recommended orchestration —
has its field names and value types fixed by `strategy.schema.json` and checked by
`validate`, which WARNS and preserves whatever it found. That is not the exception to the
paragraph above so much as the proof of it: what is pinned is the REPRESENTATION of a
recommendation, and nothing here reads a strategy and acts, enforces one, or asks whether
an agent followed it. Every other field on a step is as open as it ever was.

Moving a step
-------------

`tick` is the verb that ASSERTS progress, and what it writes is `done`. Nothing infers it
and `sb done` does not touch it — which is the design's first rule about progress and the
reason `tick` exists as a verb at all when the field beside it is edited by hand. The other
two moves are the file: `skipped` with the reason in `why`, and back to `open` with `tries`
bumped for a step being redone.

The one thing this file writes on a step's behalf is `_derive`, and it is that rule narrowed
rather than dropped. `comment` and `merge` mechanically refuse to open a PR or land one until
the change record carries the very facts the fixed skeleton's four steps exist to produce; so
having refused without them, they close those four steps themselves rather than asking
somebody to transcribe what the tool has just checked. It touches `_SKELETON`'s own defs and
no freeform step, never a step already done or skipped, and it writes `auto-tick` and never
`tick` — so the changelog still says which progress was somebody's judgement and which was
this file's arithmetic. An AMBIGUOUS signal is still a judgement and is still typed by hand.

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
renders it as PROSE rather than flattening it to one line (`_BLOCK`) — on the pull request
comment as a headed, collapsible section of its own, rendered as the markdown it was
written as, and in the walk `show <step> --markdown` still takes, quoted line by line.
Written BY HAND by the agent that did the step, as it ticks, like `gate` and unlike
`tick`: no verb writes it, because a verb would have to be exempted from both doors `_cap`
keeps — `MAX_TEXT` and the control character — and an approved contract is longer than one
and made of the other. REPLACED and never appended: a rejected contract is overwritten by
the redone one, and what records the loop is `tries` and the changelog, which is exactly
why this is not a note.

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

A definition may also OBLIGE another — `create-pr` obliges `change-approval` — and naming
it adds both. The obliged step carries `obliged_by`, the id of the step that brought it, and it can
be skipped with a reason like any other. What it cannot be is omitted: the obligation is a
property of the definition rather than a rule an agent remembers, so there is no way to name
a create-PR step and end up without the approved contract it must land against. A skip is a state with a sentence
beside it and a bad call can be questioned; an omission is invisible, which is enforcement in
appearance only. An on-the-fly step called "merge the PR" obliges nothing, and that is not a
hole — it is a word-only step, and the obligation belongs to the definition, not to the word.

Every obliging step gets its OWN obliged step, and nothing is ever deduplicated: two steps
obliging reviews are two reviewed results, whether they arrive in one act or two. A dedupe
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
`plan-review`, `review` and one template — because the design says what to promote
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
worktree is gone. It is resolved at `create` and stored. If sb did not answer then, a
later read asks again and persists any answer; a plan is never re-attached after
an answer was stored. A plugin `Context` has no store handle by design, so the resolution
is a shell-out to sb itself (`inspect` for an agent caller, `workspace list` to map this
checkout's path otherwise) — D2's sanctioned path, and the only one that returns the same
string the board uses.

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
Only `unavailable` is recomputed lazily. An answer of `none` is as final as a workspace
name, while a hiccup can repair itself without making every ordinary read a subprocess.

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
import secrets
import shutil
import subprocess
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from switchboard import config as config_mod
from switchboard import models as models_mod
from switchboard import plugins as plugins_mod
from switchboard import presets as presets_mod
from switchboard import roles as roles_mod
from switchboard.plugins import Result

# THE VOCABULARY IS READ FROM THE MODULES THAT OWN IT, never re-listed here and never
# shelled out for. `catalog` is a digest of what this repo has right now — roles, tiers,
# presets, enabled plugins, capabilities — and every one of those five already has exactly
# one definition in sb. A plugin that shipped its own copy of any of them would be an
# inventory going stale against the thing it describes, which is the one failure the whole
# generated-catalogue design exists to avoid; a plugin that ran `sb roles --json` in a
# subprocess would pay a Python interpreter per category to be told the same thing. None of
# these five imports reaches the store, herdr or the network: they read config off disk,
# which is what a read-only listing is.


# This file, rather than a parallel Python structure, is the single contract for the
# advisory strategy a step may carry. The validator below deliberately understands only
# the small vocabulary used by this schema; it is not a general JSON Schema engine.
_STRATEGY_SCHEMA = json.loads(
    (Path(__file__).resolve().parent / "strategy.schema.json").read_text(encoding="utf-8")
)

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

# What `comment` and `merge` write when they DERIVE a skeleton step's completion from a fact
# they have already refused to proceed without, rather than being told it. Its own action and
# not a second `tick`, so a reader of the changelog can always tell the progress somebody
# asserted from the progress this file worked out for itself. See `_derive`.
DERIVED = "auto-tick"

# The changelog ACTIONS that close a step, and so the only ones that stamp when one was
# finished. A separate list from the three words above on purpose: those are what a step
# SAYS and are an open vocabulary a hand-edit may add to, these are what this plugin's own
# verbs WROTE, which is a closed list and is the only thing a timestamp can be trusted from.
# A derived tick closes a step exactly as a typed one does — it is stamped by the call that
# made it and would otherwise vanish from every timing the changelog is the only source for.
CLOSING = ("tick", "skip", DERIVED)

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

# THE TWO KINDS OF DOCUMENT this store holds, and the field that tells them apart. A `plan`
# is the hand-shaped step graph this file has always held. A `record` is the change record:
# the durable landing facts a change accumulates — verification, review, PR head, human
# approval — held for a change that has NO plan, which is the ordinary direct change. Both
# live in the same `p-<n>.json` store and share its ids, locking, crash-safety, migration and
# rendering; what a `record` does not have is a HAND-SHAPED graph — it is born with the fixed
# execution+landing skeleton (`_skeleton`), and the step renderers read a record's steps and a
# plan's alike.
#
# ABSENT MEANS PLAN, which is the whole of backward compatibility for this field: every
# document written before it existed is a plan, and reads as one without being rewritten. A
# `record` is the only document that carries `kind` explicitly, because it is the only one
# that is not the thing this store started out holding.
KIND_PLAN, KIND_RECORD = "plan", "record"

# A CHANGE'S PATH: whether it was shaped (a plan was made, investigation-first) or direct (no
# plan, a bounded change that went straight to the work). It is the change record's own field
# and the first fact everything else about landing is read against — a direct change never
# gets a change-approval step, a shaped one carries its approved contract. A closed pair,
# because the PR that derives landing behaviour switches on it.
DIRECT, SHAPED = "direct", "shaped"

# THE SHAPED PLAN'S LIFECYCLE, as points a change record passes through. They DESCRIBE and
# VALIDATE the record; they execute nothing and ban no diagnostic. `shaping` is a sparse plan
# of investigation/design steps; `approval` is the combined solution/plan/contract sign-off;
# `execution` is implementation sanctioned; `review` is fresh independent review owning the
# next move; `human-review` is the PR open with only human checks left; `landing` is human
# approval against the reviewed head; `finished` is merged and cleaned up. A direct change
# has no plan and so no shaping/approval/execution — its record is `None` here until it opens
# a PR. ADVISORY AND OPEN, exactly as `progress` is: written by the owner by hand, and
# nothing here refuses or warns on a word the lifecycle does not have. The phase DESCRIBES
# the record, the agent is the interpreter of it, and a phase this file has never heard of is
# a job's own word rather than a defect. The closed list is here so a renderer or a later
# check has the vocabulary — not to police the field.
_PHASES = ("shaping", "approval", "execution", "review", "human-review", "landing",
           "finished")

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
        "planner", planner, audience="both",
        help="the plan writer's own instruction — read it on your first turn if you were "
             "spawned to write a plan")
    reg.command(
        "catalog", catalog, audience="both",
        help="the vocabulary this repo has right now — roles, model tiers, presets, "
             "enabled plugins, capabilities, the step library and the templates")
    reg.command(
        "strategy-schema", strategy_schema, audience="both",
        help="the exact field names and value types a step's `strategy` may carry — the "
             "contract `validate` checks one against")
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
              reg.arg("--planner", flag=True,
                      help="you are this plan's plan writer: records you in the plan's "
                           "`planner` field, which makes the SHAPE of the plan yours "
                           "rather than the worktree owner's until you clear it again"),
              reg.arg("--reason", help="why, for the changelog")])
    reg.command(
        "record", record, audience="both",
        help="start a change record for a DIRECT change — the landing facts, and no plan; "
             "made as soon as the work is direct and heading for a landing change",
        args=[reg.arg("title", repeat=True, help="what the change is"),
              reg.arg("--display", help="the record's board name — a display version of the "
                                        "title, one line, required"),
              reg.arg("--request", help="the human ask this change answers, carried to the "
                                        "PR"),
              reg.arg("--note", repeat=True, help="a note on the record; repeat for more"),
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
        # A DIRECT change reaches its pull request through this verb and no other, so the
        # help says "or change record" outright: a caller holding one has no plan, and help
        # that names only plans reads as a verb that is not for it.
        "comment", comment, audience="both",
        help="create or update one plan or change record's marked PR comment by its exact "
             "numeric id",
        args=[reg.arg("plan", help="the plan or change record to post, e.g. p-1"),
              reg.arg("--pr", help="the pull request number, required")])
    reg.command(
        # The landing verb, and the reason it is a verb: the approved-head-versus-live-head
        # comparison is the one check the design says must fail closed, and prose asking an
        # agent to eyeball it before a hand-run `gh pr merge` is not a check. It runs NO test
        # suite, no build and no review — by landing, all of that is recorded evidence, and
        # this consumes it.
        "merge", merge, audience="both",
        help="land the pull request a plan or change record covers — refuses unless the "
             "live head is the one the landing approval and the recorded evidence cover, "
             "then merges, records the outcome and refreshes the plan comment",
        args=[reg.arg("plan", help="the plan or change record being landed, e.g. p-1"),
              reg.arg("--pr", help="the pull request number; the record's own `change.pr` "
                                   "is the default, and a number disagreeing with it is "
                                   "refused rather than preferred"),
              reg.arg("--method", choices=("merge", "squash", "rebase"),
                      help="how GitHub merges it; `merge` is the default"),
              reg.arg("--delete-branch", flag=True,
                      help="delete the head branch once the merge lands, recorded as "
                           "`change.landing.cleanup`"),
              reg.arg("--reason", help="why, for the changelog")])
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
        help="add steps from the library — links to their definitions, never copies",
        args=[reg.arg("plan", help="a plan id, e.g. p-1"),
              reg.arg("name", repeat=True,
                      help="one or more library definitions, e.g. create-pr merge; they "
                           "land where each RUNS, so the order you type them decides "
                           "nothing"),
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

  A plan exists when the work is heading for a change that will land AND that change was
  worth SHAPING first: an investigation-first or design-first job, carried by one evolving
  plan whose approval precedes the implementation. That is the shaped path, and the rest of
  this guide is about it.

  A DIRECT change is heading for a landing change too, and it gets NO plan — no shaping, no
  change approval, none of that ceremony. It makes a CHANGE RECORD with `sb plugin plans
  record --request "..."` as soon as it is clear the work is direct and heading for a landing
  change — the same moment a shaped change is born with its record, not reconstructed once
  the PR is already open. That record is born with a fixed execution+landing STEP SKELETON —
  implementation, review, the PR, merge — so a direct change shows
  its progress on the board and its PR exactly as a plan does, without a plan's shaping half.
  (The human-only checklist is not a step of its own: `create-pr` writes it onto the record's
  `human_checks` as it opens the PR.)
  YOU DO NOT TICK THE SKELETON BY HAND. `comment` refuses to open the PR until the record
  carries the verification, the review and the human checklist, and `merge` refuses to land
  until every recorded head covers the one a person approved — so each closes the skeleton
  steps it has just confirmed, logged as `auto-tick`. Fill the record and the board follows.
  What the skeleton is NOT is a plan: it is a fixed list, not a shaped DAG, and it is not
  extended step by step — a job that needs more than the skeleton is a shaped change. The
  first call costs one line; verification, review, the PR and the human's approval fill the
  record in as the work actually produces them. Small is still the direct path and not a
  short plan: work so small it will never reach review or a PR — a typo, a one-line comment
  fix — makes no record at all, and so no skeleton.

  Everything else runs without either — investigation, questions, scouting, review-only
  work, anything a single agent answers and reports, and everything a dispatcher does.
  Investigation that becomes a change PRODUCES one of the two rather than living inside it: a
  shaped plan where the work needed shaping, a direct record where it did not.

THE CHANGE RECORD, WHICH BOTH PATHS HAVE

  Landing has facts, and they are the same facts whether or not the work was shaped: what
  was asked for, what was wrong and what was done about it, what was verified and on which
  commit, who reviewed it and what they found, what a human still has to check, which PR
  and which head, who approved the landing and against which head, and how it ended. Those
  live on the change record — one object, `change`, on the document. A shaped plan is born
  with one at `create`; a direct change gets one from `record`, and only when it needs it.

  It is EDITED BY HAND, like every other field on a plan. The only things a verb writes are
  the path, the opening `phase` a shaped plan is born in (`shaping`), `request` when
  `record --request` seeds it, and `landing.outcome` — with `landing.cleanup` — when `merge`
  lands the PR and says how that went; there is no schema to satisfy past that — put what the
  job needs on it. `sb plugin plans show` draws every field that is filled, `--markdown` puts
  them on the pull request, and `validate` reports two things and refuses neither: a shaped
  record at or past `execution` whose combined approval does not name both the plan revision
  and the contract digest, and a record at or past `landing` with no PR on it. Both are the
  same defect in two places — a record claiming to be further along than what it can point at.

  The fields, and who fills each one as they reach it:

    path         `direct` or `shaped`, written when the record is made. Everything else
                 about landing reads against it: a direct change has no plan, no contract
                 and no change approval, and never claims one.
    phase        where the work has got to, in the job's own words. The lifecycle's are
                 shaping, approval, execution, review, human-review, landing, finished; a
                 direct change has none until it opens a PR. Nothing polices what work
                 happened when — this is the record describing itself.
    request      the human's ask, in their words, for a direct change. It is what the PR
                 says the change is FOR.
    contract     the approved scope, exclusions, success conditions and constraints, for a
                 shaped one. The approved text itself stays in the approval step's `output`.
    cause        the root cause, or the feature intent where there was no defect.
    solution     what was actually done about it, and the scope boundaries worth naming.
    approval     the combined change approval as an IDENTITY — `{plan_revision,
                 contract_digest, by, at}` — recorded when Andrew approves. Shaped only.
                 Naming what was approved is what lets review and landing compare it later
                 instead of re-reading the wording.
    verification `{commit, check, environment, result, at}`. Evidence belongs to the commit
                 it ran on; that is what makes it reusable rather than re-earned.
    review       `{commit, reviewer, findings, fixes}` — the independent review, the head it
                 covered, what came back and what the reviewer fixed itself. The fresh
                 reviewer returns this structure in its report; the worktree owner writes
                 that report into the record, preserving the single-writer rule below.
    human_checks the list of things only a person can do, or the string saying none remain.
                 Written BEFORE the PR opens, so the human meets it the first time they read
                 the comment.
    pr           `{number, head}`.
    landing      `{head, by, at, outcome, cleanup}`. You write the first three — the human's
                 landing approval and the head it covers. `merge` writes the last two, and
                 REFUSES to land until the head it is about to merge is the one those and the
                 evidence above all name.
    scope, limitations, baseline, handoff
                 optional, absent until used: important scope boundaries, known relevant
                 limitations, evidenced pre-existing failures, and `{from, to, at}` when a
                 fresh main took the work over.

  WHY IT IS SEPARATE FROM THE PLAN. Review, evidence, PR rendering and landing safety are
  things a CHANGE has, not things a plan has, and binding them to a SHAPED plan would have
  meant either inventing one for every bounded fix or leaving direct work without any of
  them. So a direct change reaches its PR, its review and its merge through this record and
  no shaped plan at all — carrying only the fixed execution+landing skeleton it is born with,
  which is a legible progression and not a plan to shape.

  HOW IT REACHES THE PULL REQUEST. `sb plugin plans comment <record> --pr <PR>` posts the
  record as one marked comment and edits that same comment every later time it is run —
  the same command a shaped plan gets handed by its `create-pr` step, and on the direct
  path the only thing that puts the record in front of a human. Run it as the PR opens,
  and again whenever what that human should see materially changes: a reviewer's fix, the
  reviewed head moving, a landing decision.

AFTER THE PR IS OPEN — FEEDBACK, AND A HEAD THAT MOVED

  Two things that happen between the open PR and the merge. Both are EDGES between steps
  rather than the business of any one of them, which is why they are written here and not in
  a definition. Neither is a restart, and the whole of both is knowing what NOT to redo.

  A HUMAN REPORTS A PROBLEM from the manual checks. Record what they actually saw and where
  — the observed behaviour and the environment, in their words rather than in your reading
  of them — and return it to the main agent as a defect on a live path. Fix the COHERENT
  CAUSE and not the symptom they happened to hit. Then rerun ONLY the verification and the
  review facets that fix touched, update the same PR comment, and ask the person to repeat
  only the manual checks the fix invalidated. Unrelated testing and review are NOT restarted
  because the PR went back to implementation: evidence for what the fix did not touch is
  still evidence, and asking somebody to redo a check that still holds is the cost this
  design exists to remove.

  THE HEAD MOVED AFTER THE LANDING APPROVAL, which is the other one, and A DIFFERENT COMMIT
  HASH IS NOT BY ITSELF A REAPPROVAL. Code and configuration changes get the verification and
  review they affect; human checks are repeated only where the behaviour they cover changed.
  Ask for RENEWED landing approval when the behaviour, the risk, the evidence or the reviewed
  result materially changed — and do NOT ask for one where the move cannot affect the change:
  a rebase onto an unrelated main, a commit message, a metadata-only edit. The trigger is
  INVALIDATED JUDGEMENT, not a different hash. Whichever it is, the record carries it:
  `verification` and `review` name the commit each covers and `landing.head` names the head a
  person approved, `merge` refuses to land until those agree, and a renewed approval is those
  fields being rewritten rather than a conversation somebody remembers.

WHO WRITES TO IT

  The worktree's owner: the lead, or the sole worker where there is no lead. A sole worker
  counts as a lead for this and nothing else — planning the work you were given is how the
  task is carried, not work you took on.

  The owner makes every edit to the SHAPE of the plan — steps, order, owners, gates, deps.
  A child that wants one ASKS, with `sb tell parent`, and does not edit the file. One
  writer is what makes editing this file by hand safe, and it is the only thing that does.

  UNLESS THE PLAN NAMES A PLANNER, which is the one thing that moves that writer, and it
  moves it temporarily. A `planner` field says the SHAPE of this plan is that agent's for as
  long as the field is there: scope, success criteria, the decomposition, cross-step deps,
  `strategy`, the verification strategy and the termination condition. Execution state —
  progress, notes, evidence, checkpoints, outputs and the ticks — never moves with it, and
  the agents doing the work record a local adaptation as a note rather than by reshaping the
  plan.

  THE FIELD IS THE HANDOVER, and each half is written by whoever is giving something up. You
  write `"planner": "<its exact agent name>"` into the plan file when you hand the shape to a
  plan writer; it clears the field, with a `note` saying so, when it hands the shape back.
  (`create --planner` writes it too, for a planner creating a plan from nothing — not the
  ordinary case, since the plan exists before the planner does.) An empty field is this
  section's ordinary rule again, unchanged: the worktree's owner writes the shape. While the
  field is filled, anything material goes to that agent BY NAME with `sb tell` — `parent`
  reaches you, not it.

  A plan with no `planner` is the ordinary case. The plan writer's own instruction is
  `sb plugin plans planner`, and the vocabulary it plans against is `sb plugin plans
  catalog`.

  TICKING IS NOT THAT. Any agent ticks the step it did, and is trusted to tick only that
  one. An agent that reports back without ticking leaves the tick to the lead, who does it
  on the report — or, if the step is not actually done, does something else about it.

  A dispatcher is never involved in a plan. It relays work and makes agents and worktrees;
  it does not plan, own, tick or read one.

SPAWNING A PLANNER, AND WHO RUNS THE PLAN AFTERWARDS

  A planner is worth an agent when the shaping produced real alternatives, a wide blast
  radius, work crossing subsystems, or verification that is expensive or uncertain — the
  cases where a fresh reader challenging the approach changes the plan. Bounded work with an
  obvious approach does not get one: you write the short plan yourself, and a planner added
  to work of that size is the process this design exists to remove.

  THE PLAN EXISTS BEFORE THE PLANNER DOES. You created it at shaping entry and it holds what
  the shaping found; the planner EXPANDS that one in place and never creates a second. Hand
  it the shape with the `planner` field above, and give it a brief carrying the job in a
  sentence, the plan id, the files in and out of scope, the decisions already settled, and
  what you want challenged.

  SEED IT SMALL. Spawn the first-class `planner` role. Its shipped template is strong and
  holds `spawn` so it can put up its own plan reviewer; grant `fork` only where an isolated
  helper is actually foreseen. NEVER `write-tracked`: a planner reads and does not write
  tracked files, and its own writes — the plan file (under the git common dir's
  `agentflow/`, via `sb`) and its briefs (under `.switchboard/`, gitignored) — are neither
  of them tracked. A reviewer it spawns is seeded from that same set and so arrives without `write-tracked` too, which points the plan-review
  boundary the right way — but it is not a wall, and nothing here should be relied on as one:
  the plan file is not a tracked file, no write is refused anywhere, and what actually keeps
  a plan reviewer off the plan is the instruction it is given.

  SEEDING IS TWO VERBS, and neither is a flag on the other. `sb delegate --role <role>` sets
  the child's ROLE TEMPLATE, which is the seed narrowed by the template/intersection rule;
  `sb grant <agent> <cap>` adds anything beyond that template. There is no `delegate --grant`.
  A capability you cannot supply is a precondition — resolve it before the spawn, not at it.

  IT HANDS THE SHAPE BACK AND FINISHES. The planner clears the `planner` field, tells you
  what it wrote and what it challenged, and calls `sb done`. It does not stay open, it does
  not take the plan to Andrew, and it does not spawn whatever runs the plan. From there the
  shape is yours again: you put the two sections to Andrew at `change-approval`, and a
  rejection or a later material delta comes to you — you decide whether to make the change
  yourself or spend a fresh planning pass on it.

  WHO RUNS THE PLAN IS THEN YOUR CALL, AND CONTINUING IS THE DEFAULT. You already hold the
  problem, the decisions and the risks, so carry on as the agent that executes it. A fresh
  main agent is an option that has to earn itself: shaping consumed most of your context,
  execution needs capabilities or a specialism you do not have, or the execution is large
  enough to deserve its own accountable owner. When you do use one, YOU spawn it — a fresh
  main is your child and never the planner's, because `sb delegate` only ever makes the
  caller's own child and a planner that finishes would orphan it — and you hand it the
  approved design, the plan, the contract, the constraints and the open risks rather than a
  compressed sentence. Record it on the change record's `handoff`, which exists for exactly
  this and is absent when it did not happen.

  WHERE THE PLAN LIVES. In the one workspace you and the planner share — yours. An isolated
  main uses the same repo-state plan by qualified id (`p-<n>/step-<n>`) while the plan stays
  attached to that workspace.

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

  IN ONE CALL IF YOU CAN, because a call is what sorts. `create --lib` and `name-step`
  both take several names and place them where each RUNS; a step added by a LATER call —
  or written into the file — is placed against the plan AS IT THEN STANDS, and nothing
  already in the plan is ever re-deped. So `name-step p-1 merge create-pr` is right
  whichever way round you type it, while `name-step p-1 merge` and then `name-step p-1
  create-pr` leaves the merge waiting on the implementation, because that is what the plan
  ended with when it was named. Name them together, or fix the edge in the file
  afterwards, which is one field.

  NAME EVERY OUTERMOST STEP, AND WHAT EACH OBLIGES ARRIVES WITH IT — the library has FOUR
  steps nothing else brings, `implementation`, `create-pr`, `merge` and `plan-review`, and
  naming one never brings another. Three of them are the landing and review roots a shaped
  plan must not truncate; `implementation` is the work step itself — the first step of the
  fixed skeleton a DIRECT change is born with, and available to name where a shaped plan
  wants the library's version rather than its own freetext work steps. The two flags above
  land six steps, because `create-pr` obliges the change approval, which obliges the
  implementation review; `merge` is the landing step itself. (The human-only checklist a PR
  carries is not a step — `create-pr` writes it onto the change record as it opens.)
  `create-pr` on its own lands three of those and the plan ends at the open PR, which is right
  for a job that ends there — and nothing downstream can tell that plan from one
  which meant to land and lost its merge, so the naming is where it has to be got right.
  Naming an obliged step as well gets you a SECOND copy of it: nothing is ever
  deduplicated, since two obliging steps represent two outcomes and get two checks. Read `library`
  first and name the ones nothing else brings.

  A definition carries its own account of how that step is run — what it obliges, what it
  gates, what finishing it means. Read it there, AND READ IT AGAIN WHEN THE STEP COMES DUE:
  that account is an instruction that falls due at run time, not a description read once at
  compose time and then worked from memory. `tick` and `skip` print the next step's
  definition in full as they unblock it, and `show <step>` asks for one on purpose — a step
  worked from a compose-time memory of its definition is where the gate gets run after the
  code and the plan comment never gets posted. Nothing about any particular step is
  repeated here, so that nothing here can be out of date about one. The one exception is
  the section below, and it is an exception for a reason: an EDGE between two definitions
  belongs to neither of them, so no definition can be the only place it is written down.

  A STEP IS A UNIT OF WORK AND NOT AN AGENT BOUNDARY. One agent normally owns a run of
  steps and stays with them across implementation, verification, fixes and integration;
  another agent is worth its brief and its wait where the separation buys independence, a
  specialism or real parallelism. Independent review is the exception that always buys it —
  a fresh agent that did not write the change — and it is the one step whose owner is
  decided for you.

  Then re-plan on what you now know, rather than executing a split you decided before you
  knew anything.

TWO STEPS IN ONE BAND GET NO EDGE, AND `plan-review` IS WHERE YOU MEET THAT

  An anchor places a step after the band BELOW it and never beside it, so two definitions
  sharing a band are both minted as marked starts with nothing between them. Where that
  order matters, the edge is yours to write.

  `plan-review` is the case in the shipped library, and it is OPTIONAL: like `create-pr`
  and `merge`, nothing composes it and nothing obliges it, so it is in a plan because
  whoever holds the shape — a plan writer where there is one, otherwise you — decided the
  planning risk earned a fresh agent reading the whole plan first. Meaningful tradeoffs in the approach,
  a plan crossing subsystems, several agents or handoffs, verification that is expensive or
  incomplete, a large blast radius. A small linear plan does not get one and goes straight
  to Andrew at `change-approval`, which is the shape most jobs are.

  WHEN IT IS IN THE PLAN, wire it in the same edit that adds it: the `plan-review` step's
  id goes in `change-approval`'s `deps`, and that step's `root` goes to false. It shares
  the `design` band with the approval, so neither half is drawn for you — and a step
  carrying a start mark AND a dep is a defect `validate` reports, which is why the two go
  together. Left unwired, the plan reads as one whose approval can be reached without the
  review.

  The reviewer reports to whoever holds the shape and touches neither the plan nor the
  approval; that agent resolves the findings, puts a compact result in the step's `output`
  and ticks it. A rejection at the approval goes back to whoever holds the shape THEN —
  which is you, unless a planner is still engaged — with `tries` bumped and the approval
  reopened, and the review runs again only where the revised planning risk earns it. The
  definition is the detail — `sb plugin plans library plan-review`.

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
    strategy     the recommended way to run this step, written by whoever shaped the
                 plan — a plan writer where there is one. A sparse object, every field
                 optional, and these nine names and no others. Seven are plain non-empty
                 STRINGS: `continuity`, `orchestration`, `model`, `isolation`,
                 `verification`, `replan_if`, and `brief` — which is a one-line path or
                 reference to a brief, never the brief itself. The other two are objects.
                 `resources` holds any of `skills`, `presets` and `tools`, each an ARRAY
                 OF STRINGS. `budget` holds `context` and `passes`, BOTH STRINGS: a budget
                 is prose a person reads, so `"one build pass, one review pass"` or `"2"`,
                 and a bare number is the mistake this list exists to stop. It is the ONE
                 field here whose names and types are fixed — `strategy.schema.json` is
                 the contract, `sb plugin plans strategy-schema` prints it, and `validate`
                 reports what does not match it, a field name it has never heard of
                 included — and it is ADVISORY: nothing reads a strategy and acts on it,
                 and no check here asks whether anybody followed one. Missing means use
                 your judgement; departing from one you were given needs no permission,
                 and only a consequential departure is worth a note.
    display      required on every step, and `deps` on every step but the first — see
                 above. The minting verbs refuse a step without a board name.

  `id`, `def`, `name`, `obliged_by` and the plan's `next_step` are MINTED and are not
  yours: a `def` typed by hand brings neither what its definition composes nor what it
  obliges, and `next_step` is the plan's own step counter, which shows up in the collapsed
  metadata of the PR comment because everything that rendering does not draw by name is
  still walked off the record rather than off a schema. A definition's `command` is not on
  the record at all — it is resolved out of the library every time the step is drawn.

  A FIELD THIS LIST HAS NEVER HEARD OF IS ALLOWED. Apart from `strategy` above there is no
  schema to satisfy: put what the job needs on the step, and `show`, `--json` and the PR
  comment all print it — a scalar gets its own line under the step in the terminal, and
  anything with a shape to it is left to `--json`, which is the rendering that can carry
  one. What `validate` says about a `strategy` is the same kind of thing it says about a
  missing board name: a defect reported, never a refusal, and never data thrown away.

  Three verbs are worth typing rather than editing, being frequent, small and usable by
  the agent that did the work rather than only by the plan's owner — `tick <step>` when a
  step is done, `skip <step> --why "<reason>"` when it is not going to be, and `note
  <step> --text` for what happened. A `tick` or a `skip` also prints what it just
  unblocked, in full, so the next step's own instructions arrive as you reach it. `sb
  plugin plans show <step>` is that same view of one step asked for on purpose — the step,
  its command, and how its definition says it is done. `sb plugin plans --help` lists the
  rest.

  DEPS SAY WHEN A STEP RUNS, NOT WHEN IT MAY. Running one ahead of its deps is allowed and
  is sometimes the right call — a slow external check worth queueing early, a machine that
  is briefly awake — and nothing refuses it or warns on it. What the early start does not
  change is that IT IS STILL THE WHOLE STEP: everything the definition says that step does
  still applies, and none of it is excused by having begun before its turn. Where a half of
  it genuinely cannot be finished yet, `note` that half as outstanding and say what it
  waits on — a note saying only what you did reads as a decision, and a step half-done and
  described as a decision is one nobody downstream knows to finish.

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


def strategy_schema(ctx, args) -> Result:
    """Print the strategy contract itself. Reads nothing at call time and writes nothing.

    THE GUIDE SAYS THE SAME THING IN PROSE, and that is the read a plan writer is already
    doing; this verb is the machine-readable half of it, for a caller that wants the field
    names and types as data rather than as a paragraph. Both come from this one file —
    `strategy.schema.json` is loaded once at import and is what `validate` checks against —
    so the guide's prose is the only copy that can drift, and a test pins it to this.

    Printed as the JSON it is rather than as a rendering of it: the whole value of asking
    for the contract is getting the contract, and a prettified summary would be a second
    description of the schema sitting next to the guide's.
    """
    return Result(human=json.dumps(_STRATEGY_SCHEMA, indent=2, ensure_ascii=False),
                  data={"strategy_schema": _STRATEGY_SCHEMA})


# -- the planner package -------------------------------------------------------
#
# THREE THINGS A PLAN WRITER READS, and only the first is new prose. `planner` is the
# instruction it reads once, on its first turn; `guide` is how a plan is made, read at the
# start of every planning pass; `catalog` is the vocabulary it may name, generated from the
# repo rather than written down anywhere. The split is the same one the guide and the
# spawn trigger already make: what is read once, when a job comes up, is not paid for on
# every spawn — `planner.md` is NOT in `agent.md` and nothing carries it.
#
# All three live in the plugin so that deleting it takes every planner-specific surface
# with it. Its first-class role lives under this plugin's `roles/` directory for the same
# reason; what remains is plan data already in the repo, which goes inert.

# The instruction's own file. A file rather than a Python string, unlike `GUIDE`, because
# it is the length of a role prompt and is edited far more like one: the comment block at
# its top is for whoever edits it and is dropped on the way out (`config.prose`), exactly
# as `sb presets <name>` drops a preset's.
PLANNER = "planner.md"


def planner(ctx, args) -> Result:
    """Print the plan writer's instruction. Reads one file, writes nothing.

    A verb rather than a preset for `guide`'s reason: a preset survives the plugin being
    deleted and this text names commands that would then not dispatch. Read on the
    planner's FIRST TURN and carried on no spawn — a planner-specific instruction stapled
    to every agent in the fleet would be paying, forever, for the jobs that have no plan
    writer.
    """
    path = Path(__file__).resolve().parent / PLANNER
    text = config_mod.read_text(path)
    if text is None:
        # Said with the path, like every other unreadable file here. An empty answer would
        # leave a planner believing it had read its instruction and found nothing in it.
        why = (f"{path} is not readable, so there is no planner instruction to print. "
               f"Restore the file or reinstall the plugin.")
        return Result(ok=False, human=why, data={"error": why})
    body = config_mod.prose(text).rstrip("\n")
    return Result(human=body, data={"planner": body, "path": str(path)})


def catalog(ctx, args) -> Result:
    """The vocabulary of this repo, right now: what a plan may name and nothing else.

    GENERATED, NEVER MAINTAINED. Every category here is read from the module that owns it
    at the moment the command runs, so a role added this morning is in it and a tier
    deleted this afternoon is not. That is the whole point of the command: a planner
    recommending a model, a preset, a capability or a step definition has to be naming
    something that exists, and the alternative to generating the list is a hardcoded
    inventory that is wrong the week after it is written.

    A DIGEST AND NOT THE DETAIL. Each section prints names and the one or two facts that
    tell them apart, plus the command that reads one in full — a role's prompt, a preset's
    prose, a definition's `about`. Dumping all of it would be most of a context window
    spent before the planning starts.

    IT COVERS SB-MANAGED VOCABULARY ONLY. Skills and tools come from the session an agent
    runs in and sb does not know them; the planner's own session already lists its own. So
    the closing line of the human rendering says so rather than leaving the omission to be
    discovered — a planner that read this as the whole inventory would invent tool names,
    which is the one failure this command exists to prevent.

    EVERY SECTION DEGRADES ON ITS OWN (`_section`). A broken `models.toml` or one
    unparseable file in `library/` costs that section and is reported in `problems`; it
    does not take the catalogue down. A planner with six categories and a named gap can
    still plan and knows what it is missing; a planner with a traceback has nothing.
    """
    repo = Path(ctx.worktree)
    problems: list[str] = []
    data = {
        "roles": _section("roles", problems, lambda: _cat_roles(repo), []),
        "models": _section("models", problems, lambda: _cat_models(repo),
                           {"default_provider": None, "tiers": []}),
        "presets": _section("presets", problems, lambda: _cat_presets(repo),
                            {"available": [], "every_agent": [], "roles": {}}),
        "plugins": _section("plugins", problems, lambda: _cat_plugins(repo), []),
        "capabilities": _section("capabilities", problems, lambda: _cat_caps(repo), []),
        "library": _section("the step library", problems, lambda: _cat_defs(_lib), []),
        "templates": _section("the templates", problems, lambda: _cat_defs(_kept), []),
    }
    data["problems"] = problems
    return Result(human=_catalog_lines(data), data=data)


def _section(what: str, problems: list[str], produce, empty):
    """One category, or an empty one and a line saying which is missing and why.

    `Exception` on purpose, and it is the one place in this file that is that wide: this
    reads five config layers and two directories through modules that raise several
    unrelated error types, and the failure mode being bought off is a planner starting its
    job with a traceback instead of a catalogue. The reason is never swallowed — it goes in
    `problems`, which both renderings print.
    """
    try:
        return produce()
    except Exception as e:                       # noqa: BLE001 — see above
        problems.append(f"{what} could not be read: {_flat(e)}")
        return empty


def _cat_roles(repo: Path) -> list[dict]:
    """Every role this repo has, merged — shipped, then its own. `switchboard/roles.py`.

    The tier and the capability template are what a planner chooses between; the prompt is
    the detail, and `sb roles <name>` is where it is read.

    BOTH READ OFF THE RESOLVERS the seeder and the config gate read them off —
    `template_capabilities` and `template_ceiling` — rather than off a Role's raw fields,
    which is the same rule `sb roles` keeps and for the same reason: a listing holding its
    own idea of "what a lead gets" is how two readouts of one fact come to disagree. Not
    `is_top`, because a role is not a placement: the top's fixed set belongs to the stamp,
    and printing it against `dispatcher` would advertise something no `--role dispatcher`
    spawn is seeded with.

    `config_ceiling` travels in `--json` and not in the digest: how far an agent may tune
    itself matters to about one plan in fifty and is a column in the way for the rest.
    """
    got = roles_mod.load(repo)
    return [{"name": name,
             "model": role.model,
             "capabilities": sorted(roles_mod.template_capabilities(
                 got, name, is_top=False, repo=repo)),
             "config_ceiling": roles_mod.template_ceiling(got, name, repo=repo)}
            for name, role in sorted(got.items())]


def _cat_models(repo: Path) -> dict:
    """The resolved tier table. What `sb models` prints, minus the CLI flags.

    A tier NAME is what a plan may recommend — `strong`, `cheap` — and the resolved model
    behind it is what says whether two tiers differ by anything a plan should care about.
    `cli_args()` is deliberately not called: an unwired provider is a spawn-time problem
    and `sb models` is where it is reported, and calling it here would make a listing raise
    over a tier nobody in this plan was going to name.
    """
    tiers = models_mod.load(repo)
    out = []
    for name in tiers.names():
        spec = tiers.resolve(name)
        out.append({"name": name, "provider": spec.provider, "model": spec.model,
                    "effort": spec.effort})
    return {"default_provider": tiers.default_provider, "tiers": out}


def _cat_presets(repo: Path) -> dict:
    """The presets and who already carries them. `switchboard/presets.py`.

    Both halves matter to a plan: a preset a step should name, and what a spawn of that
    role is bound to already — recommending a preset every agent carries anyway is advice
    that costs a line and buys nothing. The binding lists are verbatim, `@<plugin>` entries
    included, because that is what a spawn actually resolves and this listing does not get
    to tidy the record.
    """
    every, per_role = presets_mod.bindings(repo)
    return {"available": sorted(presets_mod.available(repo)),
            "every_agent": list(every),
            "roles": {role: list(names) for role, names in sorted(per_role.items())}}


def _cat_plugins(repo: Path) -> list[str]:
    """The plugins whose verbs dispatch in this repo. Enabled, not available.

    Available-but-disabled is exactly the trap this command exists to close: a plan
    recommending `sb plugin todo add` in a repo that never enabled `todo` reads as a
    checked decision and is a command that refuses.
    """
    return list(plugins_mod.enabled(repo))


def _cat_caps(repo: Path) -> list[str]:
    """Every capability string this repo has a meaning for — what `sb grant` will accept.

    THE DEFINITION IS `Broker.known_capabilities`, and this is the same three parts in the
    same order: the shipped vocabulary, plus every capability this repo's own role
    templates name, plus the side-effect capabilities it declares, minus `start` — which is
    a hardcoded human-only gate and must never become grantable. Getting any of those wrong
    would be a planner recommending a grant that refuses, or missing one a repo minted for
    itself.

    IT IS THE SAME PARTS RATHER THAN THE SAME CALL, and that is a deliberate trade. A
    plugin holds no `Broker` — no store handle and no herdr, by design — and the ways to
    reach that method from here were a subprocess per category or a stand-in object bound
    to three of its private helpers, which is a coupling that breaks silently the day one
    of them moves. So the vocabulary is assembled from the module that owns each part, and
    `test_plans_plugin` pins this list equal to a real broker's: the day the two definitions
    diverge, a test says so.

    A repo whose side-effect table will not parse gets the rest of the vocabulary rather
    than none of it, which is the broker's own behaviour at the same point.
    """
    got = roles_mod.load(repo)
    template = set().union(*(r.capabilities for r in got.values())) if got else set()
    try:
        declared = set(roles_mod.side_effect_capabilities(repo))
    except config_mod.ConfigError:
        declared = set()
    return sorted((set(roles_mod.CAPABILITIES) | template | declared) - {"start"})


def _cat_defs(loader) -> list[dict]:
    """`library/` or `templates/` as a listing: what each is called and what it is.

    Through the same `_lib`/`_kept` the verbs use, so a file this plugin refuses to resolve
    is refused here too rather than half-read — and turned back into an exception so that
    `_section` reports it as one broken category instead of a refused command. A catalogue
    is the last thing that should stop being generated because one JSON file has a comma
    in the wrong place.
    """
    got, bad = loader()
    if bad:
        raise _BadDef(bad.human)
    out = []
    for key, spec in got.items():
        spec = spec if isinstance(spec, dict) else {}
        out.append({"name": key,
                    "display": str(spec.get("display") or "").strip(),
                    "about": str(spec.get("name") or spec.get("title") or "").strip(),
                    "anchor": str(spec.get("anchor") or "").strip()})
    return out


# The command that reads one entry of a category in full, printed beside the heading.
# Every planner recommendation is meant to be made off the detail rather than off this
# digest, and a listing that does not say where the detail is, is one nobody goes past.
_CATALOG_READ = {
    "roles": "sb roles <name>",
    "models": "sb models",
    "presets": "sb presets <name>",
    "plugins": "sb plugin <name> --help",
    "capabilities": "sb capabilities",
    "library": "sb plugin plans library <name>",
    "templates": "sb plugin plans template list",
}


def _catalog_lines(data: dict) -> str:
    """The digest a planner scans. `--json` is the rendering a machine reads.

    One section per category, in the order a plan is actually written in — who the agent
    is, what it runs on, what it carries, what it may do, then the steps that already
    exist. Empty sections are drawn rather than dropped: "this repo has no templates" is an
    answer, and a section that vanished would read as one the command forgot.
    """
    out = ["The vocabulary this repo has right now — generated from the repo at this",
           "moment, never a list anybody maintains. The names are exact: use them as they",
           "are spelled here, and read one in full with the command beside its heading."]
    for key in ("roles", "models", "presets", "plugins", "capabilities", "library",
                "templates"):
        out.append("")
        out.append(f"{_col(key, 16)}{_CATALOG_READ[key]}")
        out.extend(f"  {line}" for line in _catalog_rows(key, data.get(key)))
    out.append("")
    # THE HALF THIS COMMAND CANNOT SEE, said here rather than left to be discovered. sb
    # knows nothing about the skills and tools a session exposes, so a planner reading this
    # as the whole inventory would invent tool names — which is the one failure the
    # generated catalogue exists to prevent.
    out.append("Skills and tools are NOT here. They come from the session an agent runs "
               "in rather than")
    out.append("from sb, and your own session already lists yours. Name a tool for another "
               "runtime")
    out.append("only when you know that inventory; otherwise describe the capability the "
               "step needs")
    out.append("and leave the choice to the agent doing it.")
    if data.get("problems"):
        out.append("")
        out.extend(f"! {p}" for p in data["problems"])
    return "\n".join(out)


def _catalog_rows(key: str, value: Any) -> list[str]:
    """One category's rows. Each is a name and the least that tells it from its neighbour."""
    if key == "roles":
        return [f"{_col(_flat(r['name']), 14)}{_col(_flat(r['model']), 10)}"
                f"{', '.join(_flat(c) for c in r['capabilities']) or '(no capabilities)'}"
                for r in value or ()] or ["(none)"]
    if key == "models":
        rows = [f"{_col(_flat(t['name']), 14)}{_col(_flat(t['provider']), 10)}"
                f"{_col(_flat(t['model'] or '(the provider default)'), 26)}"
                f"{('effort ' + _flat(t['effort'])) if t.get('effort') else ''}".rstrip()
                for t in (value or {}).get("tiers") or ()]
        provider = (value or {}).get("default_provider")
        return (rows or ["(none)"]) + ([f"default provider: {_flat(provider)}"]
                                       if provider else [])
    if key == "presets":
        every = set((value or {}).get("every_agent") or ())
        roles = (value or {}).get("roles") or {}
        rows = []
        for name in (value or {}).get("available") or ():
            using = [r for r, names in roles.items() if name in names]
            tag = ("[every agent]" if name in every
                   else f"[{', '.join(_flat(r) for r in using)}]" if using
                   else "[named by a step, bound to nobody]")
            rows.append(f"{_col(_flat(name), 16)}{tag}")
        return rows or ["(none)"]
    if key in ("plugins", "capabilities"):
        return [", ".join(_flat(x) for x in value or ())] if value else ["(none)"]
    return [f"{_key_col(_flat(d['name']))}{_flat(d['about'] or d['display'] or '')}"
            + (f"  [runs at {_flat(d['anchor'])}]" if d.get("anchor") else "")
            for d in value or ()] or ["(none)"]


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

    `--planner` IS A CLAIM AND NOT AN ASSIGNMENT, which is why it takes no value. The
    field says who owns the SHAPE of this plan while it is set (`GUIDE`), so the only name
    that can go in it honestly is the caller's own: a name typed for somebody else is a
    claim about an agent that may not exist, made by an agent that is not it. Absent — the
    ordinary case, and every plan made before this flag existed — the worktree-owner rule
    applies unchanged.

    IT IS NOT THE USUAL WAY THE FIELD GETS WRITTEN, since the shaped path creates the plan
    before a planner exists: the task owner writes the name into the file when it hands the
    shape over and the planner clears it when it hands the shape back, each half written by
    whoever is giving something up, both of them ordinary field edits like everything else
    on a plan. The flag covers the case this verb can honestly cover — a plan writer
    creating a plan from nothing — and nothing here reads the field as permanent.
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
    if getattr(args, "planner", False) and not ctx.agent:
        # Refused rather than filed under `human`, because the field names the agent a
        # later delta and a later approval go back to, and there is no such agent here.
        why = ("--planner records the CALLING AGENT as this plan's plan writer, and sb "
               "resolved this caller to a human. Create the plan as the planner, or write "
               "`\"planner\": \"<agent>\"` into the plan file, which is one field.")
        return Result(ok=False, human=why, data={"error": why})
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
        plan = {"id": f"p-{doc['next_plan']}", "kind": KIND_PLAN,
                "workspace": where, "workspace_from": how,
                "checkout": str(_here(ctx)), "title": title, "display": display,
                "next_step": 1, "steps": [], "changelog": [],
                "notes": [_note(n, who) for n in notes],
                # A created plan IS a shaped change: `create` is shaping entry, so the change
                # record is born here (`design`: "shaped change creates the record and sparse
                # plan at shaping entry"). Born sparse — nothing but `path`/`phase` until a
                # landing fact lands — and rendered only once it holds one, so a fresh plan
                # reads exactly as it did before the record existed.
                "change": _change(SHAPED),
                "created_by": who, "created_at": int(time.time())}
        if getattr(args, "planner", False):
            # ABSENT AND NOT NULL when there is no planner. A plan carrying `planner: null`
            # would render a field on every plan in the repo to say that nearly all of them
            # have no plan writer, and `_some` already treats the two as the same absence
            # everywhere else in this file.
            plan["planner"] = who
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
        if plan.get("planner"):
            # In the append-only record as well as in the field: who owns a plan's shape is
            # the kind of thing somebody reads a changelog to find out, and the field alone
            # says who owns it NOW rather than that it was claimed at the plan's first act.
            detail += f"; planner-managed by {_flat(plan['planner'])}"
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


def record(ctx, args) -> Result:
    """A change record for a DIRECT change — the landing facts, and no plan.

    The direct path is the ordinary one: a bounded change that went straight to the work,
    with no plan to shape and no change-approval step to sit in front of it. It still has to
    land, and landing has facts — a verification, a review, a PR head, a human's approval —
    that the design says are a change's concern whether or not a plan exists. This verb is
    where a direct change gets somewhere to keep them, and the whole point of Phase 3 is that
    it does not need a plan to do so.

    MADE ONLY WHEN LANDING METADATA IS NEEDED, which is what keeps a direct change direct: a
    bounded fix that is reviewed and reported without a PR never makes one of these, and a
    dispatcher's relay never does either. It is the same store, the same `p-<n>` ids, the same
    locking and crash-safety as a plan — a record carries a FIXED skeleton rather than a
    hand-shaped graph, so `create-pr`, `merge` and `comment` name it exactly as they name a
    plan.

    BORN WITH THE SKELETON. The record is born on the `direct` path AND with the fixed
    execution+landing skeleton (`_skeleton`) — implementation, review,
    the PR, merge — so the change is legible on the board and its PR the moment it exists,
    without a plan's shaping half. `--request` seeds the human ask it exists to carry to the
    PR; everything else — the verification, the review, the PR head, the approval, the
    landing — is written into the file by hand as the change reaches each one, and the
    skeleton's steps are ticked as they are done, the way every field and step on a plan is.
    """
    title = " ".join(str(w) for w in (args.title or ())).strip()
    display = str(args.display or "").strip()
    request = str(getattr(args, "request", None) or "").strip()
    notes = [str(n).strip() for n in (args.note or ()) if str(n).strip()]
    bad = _cap(title, display, request, *notes, args.reason)
    if bad:
        return bad
    if not display:
        return _no_display(
            "a change record", "It owns the board's whole header line, so it is a display "
            "version of the title: `--display \"raise the upload timeout\"`.")
    # The catalogue BEFORE the write, exactly as `create --lib` reads it first: the skeleton's
    # steps are NAMED (they carry a `def`), so their labels and commands resolve from the
    # library, and the return rendering needs it to draw them as words rather than as raw keys.
    # Read before the lock so a broken shipped definition refuses cleanly rather than over a
    # record already written.
    lib, bad = _lib()
    if bad:
        return bad
    with _minting(ctx.state_dir):
        doc, seal = _read(ctx.state_dir)
        who = ctx.agent or "human"
        where, how = _workspace(ctx)
        rec = {"id": f"p-{doc['next_plan']}", "kind": KIND_RECORD,
               "workspace": where, "workspace_from": how,
               "checkout": str(_here(ctx)), "title": title, "display": display,
               "next_step": 1, "steps": [],
               "changelog": [], "notes": [_note(n, who) for n in notes],
               "change": _change(DIRECT),
               "created_by": who, "created_at": int(time.time())}
        # BORN WITH THE SKELETON. A direct change is no longer stepless: it carries the fixed
        # execution+landing skeleton (`_skeleton`) so it is legible on the board and its PR,
        # composed here at birth — the one moment a record is made, and only made when landing
        # metadata is needed, so a typo that never opens a PR still makes no record and no
        # steps.
        _skeleton(rec)
        if request:
            rec["change"]["request"] = request
        doc["next_plan"] += 1
        detail = f"direct change record; {_count(rec['steps'])} skeleton"
        if how == UNAVAILABLE:
            detail += "; workspace unresolved — sb did not answer"
        _log(rec, who, "record", args.reason, detail)
        _reserve(ctx.state_dir, doc, rec)
        doc["plans"].append(rec)
        _write(ctx.state_dir, doc, seal)
    return _plan_result(_shown(rec, lib), path=_path(ctx, rec))


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
    doc, seal = _read(ctx.state_dir)
    plans, here = doc["plans"], _here(ctx)
    if not args.all:
        plans = [p for p in plans if _same(p.get("checkout"), here)]
    _repair_workspaces(ctx.state_dir, doc, seal, plans)
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
    doc, seal = _read(ctx.state_dir)
    plan = _find(doc, args.id)
    if plan is None:
        return _missing(doc, args.id)
    _repair_workspaces(ctx.state_dir, doc, seal, [plan])
    # Resolved HERE and never in the file: this is the moment a link becomes text, which is
    # why an edit to a definition reaches a plan that was made last week and is running now.
    lib, bad = _lib([plan])
    if bad:
        return bad
    md = bool(getattr(args, "markdown", False))
    return _plan_result(_viewed(_shown(plan, lib), _Live(ctx), tokens=md), markdown=md)


# WHAT OPENING A PR WAITS ON, in the order `create-pr`'s own definition names them: the key
# on the change record, what it is called in a refusal, and what has to be there.
_BEFORE_PR = (
    ("verification", "the agent verification",
     "`change.verification` needs the commit the evidence covers"),
    ("review", "the independent review",
     "`change.review` needs the commit a fresh reviewer covered"),
    ("human_checks", "the human-only checks",
     "`change.human_checks` needs the list a person must run by hand, or the explicit "
     "answer that none remain"),
)


def _preconditions_before_pr(plan: dict) -> Optional[Result]:
    """Refuse to OPEN a plan's PR comment before the record carries what the PR promises.

    DESIGN-TRUTH is firm that "The PR opens only when applicable verification is current and
    no major review issue remains", and `create-pr`'s own definition spells out three
    preconditions in so many words — a CURRENT verification, a RESOLVED review, and the
    human-only checks or the explicit answer that none remain — but nothing in the tooling
    enforced any of them, so an agent could push, open the PR and post this comment with the
    review step still open. This mirrors `merge`'s fail-closed pattern one gate earlier:
    `merge` refuses to LAND without evidence covering the approved head; this refuses to OPEN
    without that evidence recorded at all.

    ALL THREE, AND NOT JUST THE REVIEW. The gate checked the review alone for a while, which
    is the quiet half of the same bug it was written to fix: the prose promised three
    preconditions and the code enforced one, and a reader had no way to see the difference.
    An unverified change could open a PR, and — worse, because it is the line a person acts
    on by closing the tab — one could open with nobody having written down what a human still
    has to check, which is exactly what `_NO_HUMAN_ANSWER` exists to admit after the fact.

    Only the FIRST post is gated — an existing comment refreshes unconditionally, so a
    reviewer's fix, a moved head or a landing decision still updates the one comment, and
    `merge`'s own post-merge refresh (where all three are long since recorded) is never
    blocked. And only a landing CHANGE RECORD is gated: a legacy plan with no `change` has no
    fields to read and is left alone. "No unresolved major" stays the owner's judgement in
    `change.review.findings` prose — unreadable by a machine and unchecked here exactly as
    `merge` leaves it; what this checks is that each of the three was done and recorded at all.
    """
    change = plan.get("change")
    if not isinstance(change, dict):
        return None
    missing = []
    for key, what, how in _BEFORE_PR:
        got = change.get(key)
        # The two evidence fields are objects naming the commit they cover; `human_checks` is
        # a list or the sentence saying none remain, so anything there at all is an answer —
        # WHAT it says is the writer's judgement and is not read here, exactly as the review's
        # findings prose is not.
        answered = (_some(got) if key == "human_checks"
                    else isinstance(got, dict) and _some(got.get("commit")))
        if not answered:
            missing.append((key, what, how))
    if not missing:
        return None
    why = "\n".join(
        [f"{plan['id']}: refusing to open the PR comment — the change record does not yet "
         f"carry what `create-pr` requires before a PR opens:"]
        + [f"  - {what}: {how}" for _, what, how in missing]
        + ["Record what is missing and open the PR then. Once the comment exists it refreshes "
           "freely; this gate is only the open."])
    return Result(ok=False, human=why,
                  data={"error": why, "plan": plan["id"],
                        "missing": [key for key, _, _ in missing]})


def comment(ctx, args) -> Result:
    """Create or update this plan's one durable pull-request comment.

    Identity belongs in the body because the local store may move and the command may be
    retried. The marker is an exact, otherwise invisible line scoped to the canonical long
    plan id. Once found, the write is against GitHub's numeric issue-comment id — never
    against the current actor's latest comment. More than one match is refused because no
    ordering rule can say which duplicate is authoritative without risking another comment.

    The marker is added here rather than in `_comment`: `show --markdown` is a human-facing
    rendering with an existing contract, while this command owns the external identity.
    """
    pr = str(getattr(args, "pr", None) or "").strip()
    if not re.fullmatch(r"[1-9]\d*", pr):
        return _needs("--pr", "a pull request number is required, e.g. `--pr 181`")

    doc, seal = _read(ctx.state_dir)
    plan = _find(doc, args.plan)
    if plan is None:
        return _missing(doc, args.plan)
    lib, bad = _lib([plan])
    if bad:
        return bad

    # An issue and a pull request share GitHub's comments API. Resolve through the pulls
    # endpoint first so `--pr 123` cannot silently post onto ordinary issue 123.
    pull_endpoint = f"repos/{{owner}}/{{repo}}/pulls/{pr}"
    _, bad = _github(ctx, [pull_endpoint])
    if bad:
        return bad

    # The plan id scopes identity; the persisted random nonce makes that identity
    # unclaimable by a comment planted before the first upsert. After creation the marker
    # is visible in the comment source, but a copied duplicate only makes the next call
    # refuse its multiple exact matches — it never authorizes an overwrite.
    nonce = plan.get("pr_comment_nonce")
    if nonce is None:
        nonce = secrets.token_urlsafe(18)
        plan["pr_comment_nonce"] = nonce
        _write(ctx.state_dir, doc, seal)
    elif not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_-]{24}", nonce):
        why = f"{plan['id']} has an invalid PR comment nonce; refusing to replace it"
        return Result(ok=False, human=why, data={"error": why, "plan": plan["id"]})

    number = _num(_PLAN_ID, plan.get("id"))
    marker = f"<!-- switchboard-plan: plan-{number}:{nonce} -->"
    rendered = _plan_result(
        _viewed(_shown(plan, lib), _Live(ctx), tokens=True), markdown=True).human
    body = f"{rendered.rstrip()}\n\n{marker}\n"
    endpoint = f"repos/{{owner}}/{{repo}}/issues/{pr}/comments"

    listed, bad = _github(ctx, ["--paginate", "--slurp", endpoint])
    if bad:
        return bad
    try:
        pages = json.loads(listed.stdout or "[]")
        if pages and all(isinstance(page, list) for page in pages):
            comments = [item for page in pages for item in page]
        elif isinstance(pages, list):
            comments = pages
        else:
            raise ValueError("comment listing is not a list")
    except (json.JSONDecodeError, ValueError) as e:
        why = f"GitHub returned an unreadable PR comment listing: {e}"
        return Result(ok=False, human=why, data={"error": why, "pr": int(pr)})

    matches = [row for row in comments
               if isinstance(row, dict)
               and marker in str(row.get("body") or "").splitlines()]
    if len(matches) > 1:
        ids = ", ".join(str(row.get("id") or "?") for row in matches)
        why = (f"refusing to guess: PR {pr} has {len(matches)} comments with the exact "
               f"{marker} marker ({ids})")
        return Result(ok=False, human=why,
                      data={"error": why, "pr": int(pr), "plan": plan["id"],
                            "comment_ids": [row.get("id") for row in matches]})

    if matches:
        comment_id = matches[0].get("id")
        if not isinstance(comment_id, int) or comment_id <= 0:
            why = f"GitHub returned a marked comment without a numeric id on PR {pr}"
            return Result(ok=False, human=why, data={"error": why, "pr": int(pr)})
        action = "updated"
        target = f"repos/{{owner}}/{{repo}}/issues/comments/{comment_id}"
        changed, bad = _github(ctx, ["--method", "PATCH", target, "--input", "-"],
                               body=body)
    else:
        # PR-OPEN GATES ON THE RECORDED EVIDENCE. The first time this comment lands on a PR
        # is the PR-open the design gates — nothing else in the tooling mediates the raw push
        # and `gh pr create` that create the PR itself, so this is the moment to fail closed.
        bad = _preconditions_before_pr(plan)
        if bad:
            return bad
        action = "created"
        changed, bad = _github(ctx, ["--method", "POST", endpoint, "--input", "-"],
                               body=body)
    if bad:
        return bad
    try:
        comment_id = json.loads(changed.stdout or "{}").get("id")
    except (json.JSONDecodeError, AttributeError):
        comment_id = None
    if not isinstance(comment_id, int) or comment_id <= 0:
        why = f"GitHub {action} the plan comment but returned no numeric comment id"
        return Result(ok=False, human=why, data={"error": why, "pr": int(pr)})

    # THE OPEN IS THE FACT. This call refused to make it until the record carried the
    # verification and the review — the exit conditions of the two skeleton steps that run
    # before this one — and the human checklist, which is this step's OWN job; and the PR now
    # demonstrably carries the comment, which is the rest of it. So three steps are closed
    # here rather than left for somebody to transcribe a second time. A refresh derives
    # nothing, because a refresh confirms nothing new.
    derived: list[str] = []
    if action == "created":
        derived = _derive(ctx, plan["id"], ("implementation", "review", "create-pr"),
                          f"PR {pr} opened, which this refused to do until the record carried "
                          f"the verification, the review and the human checklist")

    long_id = f"plan-{number}"
    said = f"{action} {long_id} comment {comment_id} on PR {pr}"
    if derived:
        said += (f"\n  auto-ticked {', '.join(derived)} — the PR-open gate confirmed what "
                 f"they were waiting on")
    return Result(human=said,
                  data={"action": action, "plan": plan["id"], "pr": int(pr),
                        "comment_id": comment_id, "marker": marker,
                        "auto_ticked": derived})


def merge(ctx, args) -> Result:
    """Land the pull request one plan or change record covers, and record how it went.

    THE VERB EXISTS BECAUSE THE CHECK DID NOT. Landing used to be a hand-run `gh pr merge`
    with the approved-head-versus-live-head comparison written as prose an agent was trusted
    to eyeball, which is the one comparison the design says must fail closed. Here it is code:
    every head this change was approved and evidenced against is read off the record, compared
    against the head GitHub is holding right now, and any disagreement — or any missing piece
    of that identity — refuses before a single mutation is made.

    IT CONSUMES EVIDENCE AND NEVER RE-EARNS IT. Nothing in this path runs a test, a build, a
    lint or a review, and nothing here may ever be made to. Verification is evidence that
    belongs to the commit it ran on; by the time landing begins that evidence is on the record
    and the only honest question left is whether it still covers the head about to be merged.
    Rerunning a passing check to make the merge feel safer is the failure this verb was
    written to remove, not a precaution it forgot.

    WHAT IT COMPARES, all against `change.landing.head` — the head the human approved:

      change.landing        a human landing approval, with a `head` and a `by`. Absent, and
                            there is nothing to land against and no merge.
      change.approval       on the SHAPED path, the combined change approval naming the plan
                            revision and the contract digest it covered. Not a head, so not
                            compared to one — checked for being THERE, because a shaped
                            change landing without it is unsanctioned work becoming
                            everybody's. A direct change has none and is not asked for one.
      change.pr.head        the head the pull request was recorded at.
      change.verification   the commit the agent evidence covers.
      change.review         the commit the independent review covers.
      the live PR head      what GitHub is holding at this instant.

    A short sha is a real spelling of a head, so the comparison is a prefix match with a
    seven-character floor; anything that is not a hex sha at all refuses rather than matching
    loosely. The merge itself is sent with GitHub's own `sha` precondition, so a head that
    moves between the read above and the write below is refused by GitHub rather than by
    nobody.

    WHAT IS DELIBERATELY NOT CHECKED HERE, so that neither reads as forgotten. The required
    STATUS CHECKS are GitHub's own gate and it refuses the merge itself when they are red —
    reimplementing that comparison here would be a second, staler copy of a rule the server
    already enforces, and the refusal it sends back is recorded as the failed attempt like
    any other. And an unresolved MAJOR is prose on `change.review.findings`, written by the
    owner in the job's own words; there is no field for a machine to read one out of, and
    guessing at the text would refuse real landings and pass invented ones.

    THE ORDER AFTER THE MERGE IS THE RECORD'S. The outcome is written to
    `change.landing.outcome` before the comment is refreshed, so the comment renders the state
    the change actually ended in; a cleanup asked for runs first and lands in
    `change.landing.cleanup`. Anything that fails AFTER the merge has landed is recorded as
    the partial state it is and returned as a failure — a merge that happened and a comment
    that did not is not a success, and pretending the merge can be undone would be worse.
    """
    doc, _ = _read(ctx.state_dir)
    plan = _find(doc, args.plan)
    if plan is None:
        return _missing(doc, args.plan)
    change = plan.get("change")
    if not isinstance(change, dict):
        return _unlanded(plan, "no change record, so there is no landing approval and no "
                               "evidence to land against. Landing facts live on `change`; "
                               "record them before merging.")

    # The human's landing approval, which is the identity everything else is compared to.
    landing = change.get("landing") if isinstance(change.get("landing"), dict) else None
    approved = _sha(landing.get("head")) if landing else None
    if landing is None or not _some(landing.get("by")) or approved is None:
        return _unlanded(plan, "no human landing approval to merge against: "
                               "`change.landing` needs the `head` a person approved and the "
                               "`by` who approved it. Get the approval, record it, merge "
                               "then.", landing=landing)

    # The design-time sanction, on the shaped path only — a direct change has no plan and
    # no contract and never claims one. `validate` already draws a record at or past
    # `execution` without both halves of this as a defect; landing is where that defect has
    # to stop being a warning, because merging it is the moment the unsanctioned work becomes
    # everybody's.
    if change.get("path") == SHAPED:
        approval = change.get("approval") if isinstance(change.get("approval"), dict) else {}
        missing = [k for k in ("plan_revision", "contract_digest")
                   if not _some(approval.get(k))]
        if missing:
            return _unlanded(plan, f"the combined change approval (`change.approval`) has no "
                                   f"{' or '.join(f'`{k}`' for k in missing)}, so what is "
                                   f"about to land was never identified as sanctioned. "
                                   f"Record the plan revision and the contract digest the "
                                   f"approval covered, or do not land it.",
                             missing=missing)

    pr, bad = _pr_number(plan, change, getattr(args, "pr", None))
    if bad:
        return bad

    recorded = change.get("pr") if isinstance(change.get("pr"), dict) else {}
    bad = _covers(plan, "the recorded PR head (`change.pr.head`)", recorded.get("head"),
                  approved)
    if bad:
        return bad
    for key, what in (("verification", "the agent verification (`change.verification`)"),
                      ("review", "the independent review (`change.review`)")):
        evidence = change.get(key) if isinstance(change.get(key), dict) else {}
        bad = _covers(plan, what, evidence.get("commit"), approved)
        if bad:
            return bad

    pull, bad = _pull(ctx, pr)
    if bad:
        return bad
    live = _sha((pull.get("head") or {}).get("sha") if isinstance(pull.get("head"), dict)
                else None)
    if pull.get("merged"):
        return _unlanded(plan, f"PR {pr} is already merged on GitHub. Record the outcome on "
                               f"`change.landing.outcome` rather than merging it again.",
                         pr=pr, already_merged=True)
    if str(pull.get("state") or "") != "open":
        return _unlanded(plan, f"PR {pr} is {_flat(pull.get('state') or 'not open')} on "
                               f"GitHub, not open. Reopen it, or land a different PR.", pr=pr)
    if live is None:
        return _unlanded(plan, f"GitHub returned no head sha for PR {pr}, so there is "
                               f"nothing to compare the landing approval against.", pr=pr)
    bad = _covers(plan, f"the live head of PR {pr}", live, approved)
    if bad:
        return bad

    method = str(getattr(args, "method", None) or "merge")
    who = ctx.agent or "human"
    # GitHub's own precondition on the head, so the window between the read above and this
    # write is closed by the side that owns the branch rather than left to this process.
    merged, bad = _github(
        ctx, ["--method", "PUT", f"repos/{{owner}}/{{repo}}/pulls/{pr}/merge", "--input", "-"],
        payload={"merge_method": method, "sha": live})
    at = int(time.time())
    if bad:
        _record_landing(ctx, plan["id"], who, args.reason,
                        outcome={"result": "failed", "method": method, "pr": pr,
                                 "head": live, "by": who, "at": at,
                                 "error": _flat(bad.data.get("error") or "merge failed")})
        return Result(ok=False, data=dict(bad.data, plan=plan["id"], pr=pr, merged=False),
                      human=f"{plan['id']}: PR {pr} was NOT merged — {bad.human}. The record "
                            f"carries the failed attempt; nothing else was done.")
    try:
        landed = json.loads(merged.stdout or "{}")
    except json.JSONDecodeError:
        landed = {}
    outcome = {"result": "merged", "method": method, "pr": pr, "head": live,
               "sha": _sha(landed.get("sha")) or None, "by": who, "at": at}

    cleanup = None
    if getattr(args, "delete_branch", False):
        cleanup = _delete_branch(ctx, pull, at)

    _record_landing(ctx, plan["id"], who, args.reason, outcome=outcome, cleanup=cleanup)

    # THE MERGE IS THE FACT, and it is the skeleton's last step. Every head on the record was
    # compared against the one a person approved before a single mutation was made, so `merge`
    # is true rather than claimed. The three before it are derived too, as the safety net for
    # a record whose PR opened before this shipped or that had a step named onto it after the
    # PR existed — the same evidence was reconfirmed above, so the same justification holds.
    # Before the comment below, so the one authoritative rendering carries the ticks.
    derived = _derive(ctx, plan["id"], _SKELETON,
                      f"PR {pr} merged at the approved head {live[:12]}")

    # Last, and after the writes above, so the one authoritative comment renders the state the
    # change ended in rather than the state it was in when landing began.
    posted = comment(ctx, SimpleNamespace(plan=plan["id"], pr=str(pr)))
    outcome["comment"] = "updated" if posted.ok else f"failed: {_flat(posted.human)}"
    _record_landing(ctx, plan["id"], who, None, outcome=outcome, cleanup=cleanup,
                    log=False)

    data = {"plan": plan["id"], "pr": pr, "merged": True, "method": method,
            "head": live, "sha": outcome["sha"], "landing": outcome, "cleanup": cleanup,
            "auto_ticked": derived}
    if not posted.ok:
        return Result(ok=False, data=dict(data, error=posted.data.get("error")),
                      human=f"{plan['id']}: PR {pr} IS MERGED, and the plan comment was not "
                            f"updated — {posted.human}. Rerun `sb plugin plans comment "
                            f"{plan['id']} --pr {pr}`; do not merge again.")
    lines = [f"merged PR {pr} ({method}) at the approved head {live[:12]} — "
             f"{plan['id']} comment updated"]
    if derived:
        lines.append(f"  auto-ticked {', '.join(derived)} — the landing confirmed them")
    if cleanup and not cleanup.get("deleted"):
        lines.append(f"  branch {_flat(cleanup.get('branch') or '?')} was NOT deleted: "
                     f"{_flat(cleanup.get('error') or 'unknown')}")
        return Result(ok=False, human="\n".join(lines), data=data)
    if cleanup:
        lines.append(f"  deleted branch {_flat(cleanup.get('branch') or '?')}")
    return Result(human="\n".join(lines), data=data)


# The head comparison, and the two reasons it is not `==`. A head is written down by hand as
# often as it is copied, and a seven-character short sha is a real spelling of one — so a
# prefix match with git's own floor is what keeps a correct record from reading as a mismatch.
# What it does NOT do is match loosely: anything that is not a hex sha of at least seven
# characters is not a head at all and refuses, which is the fail-closed half of the same rule.
_SHA = re.compile(r"^[0-9a-f]{7,40}$")


def _sha(value: Any) -> Optional[str]:
    """A commit sha as this file compares them, or None for anything that is not one."""
    text = str(value or "").strip().lower()
    return text if _SHA.fullmatch(text) else None


def _covers(plan: dict, what: str, given: Any, approved: str) -> Optional[Result]:
    """Refuse unless `given` names the same commit the landing approval covers.

    One refusal shape for every head on the record, because they fail for one reason: the
    change that was approved and the change about to land are not the same change. The
    message names which of them disagreed and what to do about it, since an agent that has
    just been refused at the merge is exactly who cannot afford to guess.
    """
    head = _sha(given)
    if head is None:
        return _unlanded(plan, f"{what} does not name a commit, so nothing can be compared "
                               f"against the approved head {approved[:12]}. Record the "
                               f"commit it covers, or get the landing approval renewed "
                               f"against what is actually there.",
                         expected=approved, found=str(given or "") or None)
    if not (head.startswith(approved) or approved.startswith(head)):
        return _unlanded(plan, f"{what} is {head[:12]}, but the landing approval covers "
                               f"{approved[:12]}. REFUSING TO MERGE. Work out whether the "
                               f"move changed behaviour, risk, evidence or the reviewed "
                               f"result: if it did, rerun only the affected verification and "
                               f"review and ask for renewed landing approval; if it did not, "
                               f"record the approval against the head that is actually "
                               f"there. A different hash is not by itself a reapproval.",
                         expected=approved, found=head)
    return None


def _unlanded(plan: dict, why: str, **data) -> Result:
    """A merge refused before anything was mutated. Nothing here has written to GitHub."""
    text = f"{plan['id']}: {why}"
    return Result(ok=False, human=text,
                  data=dict({"error": text, "plan": plan["id"], "merged": False}, **data))


def _pr_number(plan: dict, change: dict, given: Any) -> tuple[int, Optional[Result]]:
    """The PR to land: the record's own, and `--pr` only where the two agree.

    The record is the authority — it is what the approval and the evidence were recorded
    against — so a `--pr` that disagrees is a typo or a stale copy of the step's command, and
    either way is the case where merging the wrong pull request is one keystroke away.
    """
    recorded = change.get("pr") if isinstance(change.get("pr"), dict) else {}
    on_record = _pr_int(recorded.get("number"))
    asked = str(given or "").strip()
    if asked and not re.fullmatch(r"[1-9]\d*", asked):
        return 0, _needs("--pr", "a pull request number, e.g. `--pr 181`")
    wanted = int(asked) if asked else None
    if on_record is None and wanted is None:
        return 0, _unlanded(plan, "no pull request on the record (`change.pr.number`) and "
                                  "none given. A change cannot land before it is on a pull "
                                  "request — record the PR, or pass `--pr`.")
    if on_record is not None and wanted is not None and on_record != wanted:
        return 0, _unlanded(plan, f"the record names PR {on_record} but `--pr {wanted}` "
                                  f"was given. "
                                  f"REFUSING TO MERGE: the approval and the evidence were "
                                  f"recorded against the PR on the record. Fix whichever is "
                                  f"wrong before merging.",
                            expected=on_record, found=wanted)
    return (on_record if on_record is not None else wanted), None


def _pr_int(value: Any) -> Optional[int]:
    """A PR number off a hand-edited record, which may be `181` or `"#181"` or nothing."""
    text = str(value or "").strip().lstrip("#")
    return int(text) if re.fullmatch(r"[1-9]\d*", text) else None


def _pull(ctx, pr: int) -> tuple[dict, Optional[Result]]:
    """The pull request as GitHub holds it right now — head, state and branch."""
    got, bad = _github(ctx, [f"repos/{{owner}}/{{repo}}/pulls/{pr}"])
    if bad:
        return {}, bad
    try:
        pull = json.loads(got.stdout or "{}")
    except json.JSONDecodeError as e:
        why = f"GitHub returned an unreadable pull request {pr}: {e}"
        return {}, Result(ok=False, human=why, data={"error": why, "pr": pr})
    if not isinstance(pull, dict):
        why = f"GitHub returned no pull request object for {pr}"
        return {}, Result(ok=False, human=why, data={"error": why, "pr": pr})
    return pull, None


def _delete_branch(ctx, pull: dict, at: int) -> dict:
    """Drop the merged head branch, and say plainly whether it went. Never raises.

    Cleanup runs after a merge that has already landed, so a failure here cannot un-merge
    anything and must not be reported as though it could. It is recorded as the unfinished
    half it is — `change.landing.cleanup` — and the verb returns a failure saying so.
    """
    head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
    ref = str(head.get("ref") or "").strip()
    if not ref:
        return {"deleted": False, "branch": None, "at": at,
                "error": "GitHub named no head branch on the pull request"}
    _, bad = _github(ctx, ["--method", "DELETE",
                           f"repos/{{owner}}/{{repo}}/git/refs/heads/{ref}"])
    if bad:
        return {"deleted": False, "branch": ref, "at": at,
                "error": _flat(bad.data.get("error") or "delete failed")}
    return {"deleted": True, "branch": ref, "at": at}


def _record_landing(ctx, plan_id: str, who: str, reason: Optional[str], *,
                    outcome: dict, cleanup: Optional[dict] = None,
                    log: bool = True) -> None:
    """Write what landing actually did onto the record, re-reading first.

    Re-read rather than reusing the document this verb opened with, because `comment` writes
    between the two calls to this and the merge nonce it may have minted must survive. The
    write is deliberately narrow: `change.landing.outcome` and `change.landing.cleanup`, and
    nothing else — `phase` stays the record describing itself in the owner's own words, which
    is what the guide says it is, and no verb here promotes it.
    """
    doc, seal = _read(ctx.state_dir)
    plan = _find(doc, plan_id)
    if plan is None:
        return
    change = plan.get("change")
    if not isinstance(change, dict):
        return
    landing = change.get("landing")
    if not isinstance(landing, dict):
        landing = {}
        change["landing"] = landing
    landing["outcome"] = outcome
    if cleanup is not None:
        landing["cleanup"] = cleanup
    if log:
        # One entry per landing attempt, stamped by the call that made it. The second write
        # of a run is the comment's result landing on an outcome already in the record, and a
        # changelog saying `merge` twice for one merge would read as two attempts.
        _log(plan, who, "merge", reason,
             f"PR {outcome.get('pr')} {outcome.get('result')}")
    _write(ctx.state_dir, doc, seal)


def _github(ctx, argv: list[str], *, body: Optional[str] = None,
            payload: Optional[dict] = None):
    """One bounded `gh api` call, returned as `(process, refusal)`.

    JSON goes through stdin so a full plan is neither shell-expanded nor exposed as an
    argument. The endpoint uses gh's repository placeholders and therefore remains scoped
    to the checkout the plan belongs to.

    `body` is the comment case and the common one — the text becomes `{"body": ...}`, which
    is the shape both the comment endpoints take. `payload` is the same door for a request
    whose JSON is not a comment: the merge endpoint's `{merge_method, sha}`, sent whole. One
    of the two at most, and neither means a GET with no stdin at all.
    """
    if payload is None and body is not None:
        payload = {"body": body}
    try:
        got = subprocess.run(["gh", "api", *argv], cwd=str(_here(ctx)),
                             input=json.dumps(payload) if payload is not None else None,
                             stdin=subprocess.DEVNULL if payload is None else None,
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        why = f"could not reach GitHub through gh: {e}"
        return None, Result(ok=False, human=why, data={"error": why})
    if got.returncode:
        detail = (got.stderr or got.stdout or f"exit {got.returncode}").strip()
        why = f"gh api failed: {_flat(detail)}"
        return got, Result(ok=False, human=why, data={"error": why})
    return got, None


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
    """Done, ASSERTED. The verb somebody types, and the only place a judgement is made.

    `sb done` does not reach this and no report ticks anything. A lead reads a child's report
    and decides; a confident child ticks its own. Both are a person or an agent typing this
    command, which is the whole point of progress never being inferred: an ambiguous
    signal — a report, a step that looks finished — is a judgement, and it is made here.

    THE ONE NARROWING, and it is not that rule repealed. `comment` and `merge` DERIVE the
    fixed skeleton's own four steps from facts they have already mechanically refused to
    proceed without — see `_derive`. Nothing is being guessed there: the tool is closing a
    step whose exit condition it just checked, rather than asking somebody to transcribe the
    check. It writes `DERIVED` and never `tick`, so the changelog still says which of the two
    happened, and it touches no step outside that skeleton.
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
    """Name library steps into a plan: links to their definitions, and their run objects.

    The plan stores `def` and leaves `name` null, so the text comes out of the library
    every time the plan is rendered and an edit to a definition reaches this plan even
    while it is running. Copying the name in here would be the same code with the design's
    central claim quietly deleted from it.

    What lands may be more than one step per name. A composite expands flat, and whatever
    the resulting steps oblige is added beside them — which is the whole of "obliged, not
    optional": there is no argument to this verb that turns it off, and the merge step and
    its review are added by the same act.

    SEVERAL NAMES IN ONE CALL, SORTED BY ANCHOR, exactly as `create --lib` sorts what it
    was given. That is what makes this verb order-insensitive rather than a trap: an
    anchor looks BACKWARDS at the plan as it stands and nothing already in the plan is
    ever re-placed (`_place`), so `name-step p-1 merge` followed by
    `name-step p-1 create-pr` leaves the merge waiting on the implementation and not on
    the PR that arrived after it. Naming both in ONE call sorts them first, so the PR is
    minted before the merge and the merge lands after it — the order they run, whichever
    order they were typed. Separate calls still mean separate acts and still place each
    against the plan of that moment: this verb can now be order-insensitive, and cannot
    make two commands into one.

    Each name is minted separately and against the plan AS IT NOW STANDS, so a later name
    sees what an earlier one landed — the same one-at-a-time rule `template` keeps for
    its entries and for the same reason.
    """
    wanted = [str(n).strip() for n in (args.name or ()) if str(n).strip()]
    if not wanted:
        return _needs("name", "a named step is named after a definition in the library")
    bad = _cap(*wanted, args.reason)
    if bad:
        return bad
    lib, bad = _lib()
    if bad:
        return bad
    # EVERY NAME CHECKED BEFORE ANY OF THEM LANDS, because this verb writes once: a second
    # name that turns out to be a typo would otherwise report a refusal over a first name
    # already in the plan, and the plan would hold half of what was asked for.
    for want in wanted:
        if want not in lib:
            return _no_def(lib, want)
        # The DEFINITION's display, since that is where a named step's board label lives
        # and where an edit to it has to reach every plan naming it. So this refusal is
        # about the catalogue rather than about the command: there is no argument here
        # that could supply one, and a copy of the label on the step would be the link
        # quietly turned into a copy.
        if not str((lib.get(want) or {}).get("display") or "").strip():
            return _no_display(f"the '{_flat(want)}' definition",
                               f"A named step draws its definition's label, so add a "
                               f"`display` to `library/{_flat(want)}.json`.")

    # NO LOCK: the step id comes from this plan's own counter in this plan's own file, so
    # the only race left is two writers on one plan — which the design answers with one
    # writer per plan rather than with a lock. See `_minting`.
    doc, seal = _read(ctx.state_dir)
    plan = _find(doc, args.plan)
    if plan is None:
        return _missing(doc, args.plan)
    if _is_record(plan):
        # A change record carries the FIXED execution+landing skeleton it was born with, not
        # a hand-shaped graph — naming further library steps onto it is what a shaped plan is
        # for. Refused at the door, the way a typo'd definition is: the skeleton is not
        # extended, and a job that needs more than it is a shaped plan.
        why = (f"{plan['id']} is a change record — it carries the fixed direct-change "
               f"skeleton and is not extended with further library steps. A job that needs "
               f"steps beyond the skeleton is a shaped plan (`create`).")
        return Result(ok=False, human=why, data={"error": why})
    added: list[dict] = []
    try:
        # STABLE, so names sharing a band keep the order they were typed — the only order
        # information there is about two steps the spine cannot separate.
        for want in sorted(wanted, key=lambda k: _anchor(lib, k)):
            made = _mint(plan, lib, want, after=tuple(_sinks(plan)))
            plan.setdefault("steps", []).extend(made)
            added.extend(made)
    except _BadDef as e:
        # Nothing was written: the refusal comes back before `_write`, and `doc` is this
        # process's own copy of the store.
        return e.refusal()
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
        plan = {"id": f"p-{doc['next_plan']}", "kind": KIND_PLAN,
                "workspace": where, "workspace_from": how,
                "checkout": str(_here(ctx)), "title": title, "display": display,
                "next_step": 1, "steps": [], "changelog": [],
                "notes": [_note(str(n).strip(), who) for n in (spec.get("notes") or ())
                          if str(n).strip()],
                # A template starts a SHAPED plan, so it is born with a change record exactly
                # as `create` is — sparse, and silent until a landing fact lands.
                "change": _change(SHAPED),
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
    does — obligations included, since a template naming a PR and forgetting its human
    checklist is exactly the memory this obligation exists to replace.

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
        # its own step and carries none of this. A gate written against an obliging step
        # belongs to that step and not to anything that came along with it.
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
    sentence. A list of bare strings copied through still renders — `_rec` reads a bare
    one as its own text — but it renders with no author, and a template's author is known
    here and worth recording.
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


def _derive(ctx, plan_id: str, defs: tuple, why: str) -> list[str]:
    """Close the fixed skeleton's own steps off a fact the calling verb has just confirmed.

    THE NARROWING OF `tick`'S RULE, and a narrowing rather than a repeal. Progress is never
    INFERRED here: an ambiguous signal — a child's report, a step that looks finished — is a
    judgement, and a judgement is somebody typing `tick`. What this does is DERIVE, from a
    fact the same call has already mechanically refused to proceed without, for the four
    steps of the fixed skeleton whose exit conditions ARE those facts. `comment` cannot open
    the PR until the record carries the verification, the review and the human checklist;
    `merge` cannot land until every recorded head covers the one a person approved. Asking an
    agent to then transcribe what the tool just checked is the second, disconnected action
    that left accurate records sitting behind boards where nothing was ever ticked.

    ONLY `_SKELETON`'S OWN DEFS, and never a freeform step: a hand-authored work step has no
    mechanical fact behind it, and inventing one is exactly what `tick` refuses to do. Never a
    step already `done` or `skipped` either — this is idempotent, and it never overrides a
    skip somebody made with a reason.

    LOGGED AS `DERIVED`, its own action, so the record honestly says which progress was
    asserted and which was worked out. Re-reads the store rather than reusing the caller's
    document, exactly as `_record_landing` does and for the same reason: `comment` writes
    between that read and this one, and that write has to survive.
    """
    doc, seal = _read(ctx.state_dir)
    plan = _find(doc, plan_id)
    if plan is None:
        return []
    who = ctx.agent or "human"
    moved: list[str] = []
    for step in (plan.get("steps") or ()):
        if not isinstance(step, dict) or str(step.get("def") or "") not in defs:
            continue
        if str(step.get("progress") or "") != OPEN:
            continue
        moved.append(str(step.get("id")))
        _log(plan, who, DERIVED, why, _progress(step, DONE, None))
    if moved:
        _write(ctx.state_dir, doc, seal)
    return moved


def _add_note(step: dict, text: str, who: str) -> str:
    step.setdefault("notes", []).append(_note(text, who))
    return f"{step['id']}: {_clip(text)}"


def _next(plan: dict, moved: dict) -> list[dict]:
    """What moving this step past just released: the steps that can now be started.

    THE MOMENT A STEP IS PICKED UP is the only moment its instructions are worth printing,
    and it is the moment nothing used to mark. A definition's `about` — the two-section
    contract a change approval is written in, what a review must and must not
    check — is the whole of how that step is done right, and `_resolve` never carried it
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
    label in the terminal, quoted in the markdown walk, and lifted clean out of every step's
    own fold into a contract section of its own in the pull request comment — so `_flat`'s
    holds everywhere else in this file is held here by where the lines go instead of by
    escaping them. Anything that is not a string is one line, which is the fallback: this
    is asked of a hand-edited field and must not raise on a list somebody put there.
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
    `--markdown` renders it as a block rather than one escaped line (`_BLOCK`) — on the
    pull request comment as the markdown it was written as, in a section of its own.
    Explicit null for the same reason `gate` and `why` are.

    `name` and `def` are the two ways a step says what it is, and exactly one of them is
    filled. An on-the-fly step owns its words; a named one owns a LINK, and its `name` stays
    null so that there is no copy of the definition here to go stale — the text is resolved
    at render time and an edit to the library reaches this step wherever it is. `obliged_by`
    is the id of the step that brought this one, which is how an obliged check says which
    outcome it belongs to and how PR7's gate will find it. Both are explicit nulls for the
    same reason `why` is.

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


def _change(path: str) -> dict:
    """The change record as it is born — the sparse landing facts a change accumulates.

    Every field the design names it owns, explicit-null so the shape is documented rather
    than guessed at, exactly as `_step` does. It is a DOCUMENT-level object, never a step
    field: the fresh-step dict is fixed and a per-step record would change it, and the
    landing facts belong to the change and not to any one step of it.

    `path` is the one fact set at birth and the one everything else reads against — `direct`
    or `shaped`. A shaped record starts life in `shaping`; a direct record has no plan and no
    phase to be in until it opens a PR, so `phase` is null and stays that way until landing.

    The identity-bound fields are null objects filled by hand as the change reaches each one,
    and each names the commit or head it covers so that landing compares an identity once
    rather than rerunning the work:

      approval      the COMBINED change approval — `{plan_revision, contract_digest, by, at}`.
                    The design-time sanction, and the reason it is an identity and not a
                    boolean: it binds implementation to the PLAN REVISION it was approved at
                    and the DIGEST of the contract that was approved, so a plan or contract
                    that moves after approval no longer reads as sanctioned. Implementation is
                    presented as sanctioned only once this is recorded (`_change_defects`).
      verification  `{commit, check, environment, result, at}`.
      review        `{commit, reviewer, findings, fixes}`.
      pr            `{number, head}`.
      landing       the merge-time `{head, by, at, outcome, cleanup}` — the human landing
                    approval on the reviewed head, and the outcome. The first three are
                    written by hand when the approval is given; `outcome` and `cleanup` are
                    written by `merge`, which refuses to run at all until `head` here, the
                    PR head, the verification and the review commits and the LIVE head are
                    all the same commit.

    `scope`, `limitations`, `baseline`, and `handoff` are NOT born here. They are optional
    and recorded only when used, so — like `planner` on a plan — they are ABSENT rather than
    null on every record. `handoff` is `{from, to, at}`, written when a fresh main takes the
    work over; the other three carry important scope boundaries, known relevant limitations,
    and evidenced pre-existing failures. `output` is not among any of these: a record dumps
    its own fields, not a step's. Written and edited by hand like every document field; no
    verb mints past `path` and the opening `phase` above, and the only two writes any verb
    makes to a record after it is born are `record --request` seeding `request` and `merge`
    recording `landing.outcome` and `landing.cleanup` — what landing actually did, which is
    the one fact about a change no hand is present to write down at the moment it happens.
    """
    return {"path": path, "phase": "shaping" if path == SHAPED else None,
            "request": None, "contract": None, "cause": None, "solution": None,
            "verification": None, "review": None, "human_checks": None,
            "pr": None, "approval": None, "landing": None}


# THE EXECUTION+LANDING SKELETON a DIRECT change is born with, in the order it runs. Every
# landing change passes through these same acts, so a direct change stops being stepless and
# carries them as real, tickable steps — the same step vocabulary a shaped plan uses, minus
# the shaping half (a direct change has no change-approval). This is what makes a direct
# change legible: the board draws these as a flowchart exactly as it draws a plan's, and the
# change record's `human_checks` field populates the PR checklist with no step of its own.
#
# A FIXED LIST AND NOT A COMPOSER. The four are named as library defs and chained linearly,
# minted DIRECTLY rather than through `_mint`/oblige: `create-pr` obliges `change-approval`,
# and composing it the obliged way would drag that shaping step into a change that must not
# have one. So the skeleton is spelled out here, in anchor order — implementation (`build`),
# then review (`review`), then the PR (`pr`), then merge (`merge`) — and nothing about it is
# configurable. THE HUMAN-ONLY CHECKLIST IS NOT A STEP: it is `create-pr`'s own job, written
# onto the change record's `human_checks` before the PR opens and rendered in the one PR
# comment, so there is no separate `human review` row for a reader to misread as Andrew's own
# review slot.
_SKELETON = ("implementation", "review", "create-pr", "merge")


def _skeleton(rec: dict) -> None:
    """Compose the fixed execution+landing skeleton onto a fresh direct change record.

    Built as plain NAMED steps — `def` set, `name` null — so each draws its label and its
    command from the library at render time, exactly as a `name-step` step does, and an edit
    to a definition reaches the record wherever it is. No `obliged_by` is set: these are not
    obliged steps waiting on an obligor, they are the skeleton itself, so `_wrong`'s
    orphaned-obligation check never fires on them. Chained linearly, each after the one
    before, which is the order they run and all the board needs to draw the chart.
    """
    prev: Optional[str] = None
    for key in _SKELETON:
        step = _step(_mint_step(rec), None, key=key)
        if prev is not None:
            step["deps"] = [prev]
        rec["steps"].append(step)
        prev = step["id"]


def _note(text: str, who: str) -> dict:
    return {"text": text, "by": who, "at": int(time.time())}


def _rec(item: Any, key: str) -> dict:
    """A stored note or checkpoint as the record every renderer here reads it as.

    Hand-editing the file IS the interface, and a hand writes the value itself —
    `"notes": ["the brief is stale"]` rather than the `{text, by, at}` a verb appends. So
    the bare value is read as the field it plainly is, with no author and no time.
    `_check` refuses those lists for not being LISTS, because every verb here appends to
    one, but it does not police what is inside: a wrong record costs one rendering, and
    refusing the whole file over it would lose the lead the ninety-nine steps that are
    fine. Falls back rather than fails, exactly as `_wrong` already reads a bare
    checkpoint and as `_step_lines` reads a field this file has never heard of.
    """
    return item if isinstance(item, dict) else {key: item}


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

    `"obliges": "change-approval"` iterates one letter at a time, and what came out of that
    was a refusal saying `'merge' obliges 'c', which is not in the step library` — technically
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
    any kind. A composite naming an obliging step twice gets two copies of what it obliges,
    for the same reason naming it twice in two separate acts does: two independently named
    units are two outcomes, and one check covering both is a lead's judgement to make by
    skipping one with a reason. Dedupe would make a step's obligation satisfiable by a step it has nothing to do
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
    obliging step waits on it. An anchored PR step obliging an unanchored checklist comes
    out the same under either rule, which is the check that this is a fix and not a rewrite.

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
    order they run — `name-step p-1 merge` and then `name-step p-1 create-pr` — leaves the
    merge waiting on what the plan ended with at the time and not on the PR that arrived
    after it. What answers that is ONE CALL: `create --lib` and `name-step` both sort the
    names they were given by anchor before minting any of them, so either verb is
    order-insensitive within a call and neither can be across two. Name them together, and
    reshape in the file where a later act genuinely has to go somewhere else.

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

    Two guards on that. It writes only onto steps THIS COMMAND MINTED, never onto a step
    already in the plan, which is the same line every other write here keeps. And it is
    skipped where the obliged step ALREADY REACHES its obliger through the deps, since a
    back-edge there is the round-one cycle rebuilt.

    THAT SECOND GUARD IS A BACKSTOP AND NOT A LIVE CHECK, said here because a reader
    otherwise cannot tell which it is and a test cannot reach it. `_owed` already requires
    the obliger to rank at or above the obliged; every dep this function writes for an
    anchored step points at a STRICTLY LOWER band, an unanchored one points only at steps
    that were in the plan before this command, and nothing already in the plan can point at
    something this command just minted — so anything reachable from the obliged step ranks
    below it, and its obliger, ranking at or above it, is not among them. It stays because
    the reasoning is about `_owed`'s rule rather than about this line, and a later change to
    that rule should meet a guard rather than a cycle.
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
        if "strategy" in step:
            out.extend((sid, problem)
                       for problem in _schema_problems(step["strategy"], _STRATEGY_SCHEMA,
                                                       "strategy"))
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
        # A DONE TICK THAT RAN AHEAD OF ITS ORDER. A dep is the plan's only statement of
        # order, so a step ticked done while a step it waits on is still open reads as
        # mis-ticked or mis-deped, and a human catches it only by seeing green downstream of
        # grey on the board. This is about the TICK — a claim the step is finished — not
        # about when work happened: running a step early is legitimate and warns on nothing
        # (the guide's DEPS SAY WHEN A STEP RUNS section), and a dep that is itself done or
        # skipped is in order. Advisory like everything in this door: it names it, refuses
        # nothing, and never auto-ticks the predecessor into a finish it did not reach.
        if str(step.get("progress") or "") == DONE:
            for d in step.get("deps") or ():
                dep = at.get(_num(_STEP_ID, d))
                if dep is not None and str(dep.get("progress") or "") not in (DONE, SKIPPED):
                    out.append((sid, f"ticked done while {_flat(str(d))}, which it waits on, "
                                     f"is still open — a dep is the plan's statement of "
                                     f"order, so a step finished before the one it follows "
                                     f"is either mis-ticked or mis-deped. Reopen this step, "
                                     f"or point the dep at the step it really follows."))
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


def _schema_problems(value: Any, schema: dict, path: str) -> list[str]:
    """Validate the tiny JSON Schema subset used by ``strategy.schema.json``.

    Problems describe representation only. In particular, nothing here interprets an
    advisory value or decides whether an agent followed it, and callers never rewrite the
    value while reporting what is wrong with it.
    """
    expected = schema.get("type")
    matches = ((expected == "object" and isinstance(value, dict))
               or (expected == "string" and isinstance(value, str))
               or (expected == "array" and isinstance(value, list)))
    if expected and not matches:
        article = "an" if expected in ("object", "array") else "a"
        return [f"{path} must be {expected}, not {type(value).__name__} — replace it "
                f"with {article} {expected} value or remove it"]

    out: list[str] = []
    if expected == "object":
        properties = schema.get("properties") or {}
        if schema.get("additionalProperties") is False:
            out.extend(f"{path}.{key} is not a recognized strategy field — remove it or "
                       f"use a field named in the strategy schema"
                       for key in value if key not in properties)
        for key, child in properties.items():
            if key in value:
                out.extend(_schema_problems(value[key], child, f"{path}.{key}"))
    elif expected == "array":
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                out.extend(_schema_problems(item, item_schema, f"{path}[{index}]"))
        if schema.get("uniqueItems") and any(
                value[index] in value[:index] for index in range(len(value))):
            out.append(f"{path} must contain unique items — remove or replace duplicates")
    elif expected == "string":
        minimum = schema.get("minLength")
        if minimum is not None and len(value) < minimum:
            out.append(f"{path} must contain at least {minimum} character"
                       f"{'s' if minimum != 1 else ''} — replace it with a long enough "
                       f"string or remove it")
        pattern = schema.get("pattern")
        # JSON Schema patterns use ECMA-262, whose `$` means the true end of the string;
        # Python also lets it match just before a final newline. This schema subset does
        # not translate regex dialects generally, but it must preserve that anchor rule.
        true_end_pattern = re.sub(r"(?<!\\)\$", r"\\Z", pattern) if pattern else pattern
        if pattern is not None and re.search(true_end_pattern, value) is None:
            out.append(f"{path} does not match {pattern} — replace it with a matching "
                       f"string or remove it")
    return out


def _defective(plan: dict) -> tuple[bool, set[str]]:
    """`_faults` as the board wants it: is the plan itself short, and which steps are.

    One set and not two, because red is red — a step drawn wrong is drawn wrong, and a
    board that coloured a missing display differently from a missing dep would be asking
    a glance to tell two shades apart to learn something the plan says in words.
    """
    short, nameless, rootless = _faults(plan)
    # A change-record lifecycle defect is not tied to a step, so it reddens the plan itself
    # the way a missing display name does, rather than a cell.
    changed = bool(_change_defects(plan))
    return short or changed, set(nameless) | set(rootless) | {sid for sid, _ in _wrong(plan)}


def _defects(plan: dict) -> list[str]:
    """The same faults as lines to print under whatever the verb was doing.

    Names the ids and the fix, because a warning that says only "incomplete" is a warning
    whose reader has to go and diff the file against a rule they have not read. Every line
    is one thing wrong and the command that puts it right.
    """
    short, nameless, rootless = _faults(plan)
    wrong = _wrong(plan)
    changes = _change_defects(plan)
    if not (short or nameless or rootless or wrong or changes):
        return []
    # "incomplete" while anything is MISSING, which is what the word means and what the
    # three doors were built for; "wrong" for the rules that came out of the removed verbs,
    # where the field is filled in and says something it may not — the change-record
    # lifecycle checks are of that second kind. Both sentences end the same way, because the
    # promise is the same one: drawn red, and never refused.
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
    out.extend(f"    change: {why}" for why in changes)
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
    and the comment draws it high up (`_defect_lines`), because somebody at a merge is who
    it was written for.
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


def _workspace(ctx, *, clock: Optional["_Budget"] = None) -> tuple[Optional[str], str]:
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
    whose worktree is gone. `create` writes
    the answer to `workspace_from`, and the four values are the whole vocabulary:
    `agent`, `workspace-list`, `none`, `unavailable`.

    Called at creation and, only for a stored `unavailable`, again on a later read.
    A shared clock lets one read repair several plans without multiplying the budget.
    """
    clock = clock or _Budget()
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


def _repair_workspaces(d: Path, doc: dict, seal: dict, plans: list[dict]) -> None:
    """Retry transient workspace misses in stored plans and persist every real answer.

    The checkout and creator stored on the plan are the context of the original question.
    Using the reader's context would misfile `show p-N` or `list --all` when it reads a plan
    from another worktree. All unresolved plans on one read share one budget; failure is
    left exactly as stored, while `none` and either named resolution stick permanently.

    This is deliberately best-effort. Workspace labelling must never make a readable plan
    fail to render, including when the late write itself cannot land.
    """
    pending = [p for p in plans
               if p.get("workspace_from") == UNAVAILABLE and not p.get("workspace")]
    if not pending:
        return
    clock = _Budget()
    changed: list[tuple[dict, Any, Any]] = []
    for plan in pending:
        checkout = plan.get("checkout")
        if not checkout:
            continue
        creator = str(plan.get("created_by") or "")
        repair_ctx = SimpleNamespace(
            worktree=Path(str(checkout)),
            agent=creator if creator and creator != "human" else None,
        )
        where, how = _workspace(repair_ctx, clock=clock)
        if how == UNAVAILABLE:
            continue
        changed.append((plan, plan.get("workspace"), plan.get("workspace_from")))
        plan["workspace"], plan["workspace_from"] = where, how
    if not changed:
        return
    try:
        _write(d, doc, seal)
    except Exception:                       # noqa: BLE001 — metadata repair, never the read
        for plan, where, how in changed:
            plan["workspace"], plan["workspace_from"] = where, how


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
            # `--all`, because dormancy is a fact ABOUT finished agents: a plan is dormant
            # once every agent on its worktree has closed, so the closed ones must be in the
            # snapshot for `condition` to see them at all. `sb status` now defaults to the
            # working set — finished rows dropped — which is right for a person reading a
            # board and wrong for this, the one reader that is asking precisely so it can
            # count the finished. `owner` reads the same snapshot and wants the closed rows
            # too, for the same reason.
            snap = _ask(self.ctx, "status", "--all", clock=self.clock)
            rows = (snap or {}).get("agents")
            self._agents = ({str(a.get("name")): a for a in rows if isinstance(a, dict)}
                            if isinstance(rows, list) else None)
        return self._agents

    def roles(self, names) -> dict:
        """The role of each agent named, off the snapshot already in hand — `{name: role}`.

        Free, and that is the whole argument for the column it fills: `role` is a field on
        the row `sb status` already returned for `owner`, so a per-step "what KIND of agent
        closed this" costs no second question and no second subprocess.

        A name sb does not mention is simply absent, exactly as `owner` refuses to read that
        scoping as a death: the snapshot is the caller's own tree, an agent closed weeks ago
        or spawned in another tree is not in it, and the renderer falls back to the agent's
        own name rather than to a blank (`_did`).
        """
        rows = self.agents() or {}
        got = {n: str((rows.get(n) or {}).get("role") or "") for n in names}
        return {n: r for n, r in got.items() if r}

    def tokens(self, names) -> Optional[dict]:
        """What these agents burned, summed off their own transcripts. None if none read.

        NOT A FIGURE SWITCHBOARD KEEPS. Nothing in the store or in herdr counts tokens; the
        only place the number exists is each agent's own Claude Code transcript, which sb
        already locates per agent (`sb inspect` -> `transcript`). So this is a read of
        somebody else's log format, and everything about it is arranged around that being
        allowed to fail: an agent out of the caller's tree is refused, an agent that never
        got a session id has no transcript, and a format that drifts parses to nothing.
        Every one of those is a smaller `seen` and never an exception.

        ITS OWN BUDGET, and it is paid only for `--markdown`. One `inspect` per agent is a
        fork each where the rest of this class asks one question for the whole render, so
        the caller only asks for this on the rendering that goes on a pull request — and it
        is bounded separately so that a slow `sb status` cannot silently spend the clock
        this needs, nor this the clock that reading owners needs.

        `seen` beside `total` is what stops a partial answer passing for a whole one: three
        agents read out of five is a real number about three agents, and the line that draws
        it says so.
        """
        names = [n for n in dict.fromkeys(str(x) for x in names) if n]
        if not names:
            return None
        clock, total, seen = _Budget(), 0, 0
        for name in names:
            # The smallest `inspect` sb will answer: both counts have a floor of one, and
            # this wants neither the terminal nor the events — only the transcript PATH.
            detail = _ask(self.ctx, "inspect", name, "-n", "1", "--events", "1",
                          clock=clock)
            path = (detail or {}).get("transcript")
            got = _burned(path) if isinstance(path, str) and path else None
            if got is not None:
                total += got
                seen += 1
        return {"total": total, "agents": len(names), "seen": seen} if seen else None

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
        its life. A later read may repair `workspace_from`, but until one succeeds this
        null still cannot support an abandoned verdict.

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


# The four keys a Claude Code turn reports its usage under. Named rather than summed over
# whatever `usage` holds, because it holds more than tokens — `iterations`, `speed` and a
# `service_tier` sit in the same dict, and a reader that added up every integer in it would
# report a token count with a stopwatch reading folded into it.
_USAGE = ("input_tokens", "output_tokens",
          "cache_creation_input_tokens", "cache_read_input_tokens")


def _burned(path: str) -> Optional[int]:
    """Every token in one Claude Code transcript. None when there was nothing to read.

    ONCE PER MESSAGE, and this is the whole subtlety of the file. A transcript is one JSONL
    record per CONTENT BLOCK and not per turn, and every block of one assistant message
    carries that message's whole `usage` dict — so summing the records doubles a real
    session's total, and by a factor that moves with how many tool calls a turn made. The
    usage is therefore banked against the message id and counted once.

    Read line by line and never loaded whole: these files run to tens of megabytes, and this
    is on the path of a command a human is waiting on. A line that does not parse is skipped
    rather than fatal — a transcript being written into as this reads has a torn last line,
    which is ordinary and is not a reason to report no tokens at all.

    None and not zero for a file that could not be opened, which is the distinction the line
    that draws this is built on: an unreadable transcript is an agent not counted, where a
    zero would be an agent that spent nothing.
    """
    seen: dict = {}
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    message = (json.loads(line) or {}).get("message") or {}
                except (ValueError, AttributeError):
                    continue
                usage = message.get("usage") if isinstance(message, dict) else None
                if isinstance(usage, dict):
                    seen[str(message.get("id"))] = usage
    except OSError:
        return None
    return sum(v for u in seen.values() for k, v in u.items()
               if k in _USAGE and isinstance(v, int) and not isinstance(v, bool))


def _viewed(shown: dict, live: _Live, *, tokens: bool = False) -> dict:
    """A resolved plan with what was read live added to the COPY, and only to the copy.

    This is where "never stored" is actually kept, so it is worth being explicit about the
    one trap in it: `_resolve` hands BACK THE STORED DICT for a step that owns its own
    words, so annotating a step in place would write an owner's status into the plan's file on
    the next command that happens to write. Every step is copied again here, and there is
    no path from anything below to `_write` at all.

    THE OTHER HALF OF THE PULL REQUEST COMMENT is added here too, and it is here rather than
    in the renderer for one reason: `_markdown` is a pure function of the plan dict and has
    no store, no sb and no filesystem, which is what lets every rendering test hand it a
    literal. So the two stats that need the world — each closing agent's ROLE, and what the
    plan burned in TOKENS — are read at this instant and put on the copy as fields, and the
    renderer just draws two more fields. `owner_status` was already exactly this.

    `tokens` is off by default and asked for only by `show --markdown`, because it is the
    one thing here that costs a subprocess per agent (see `_Live.tokens`). `list` renders a
    board and must not pay it; a terminal `show` has nowhere to draw it either.
    """
    steps = [dict(s, owner_status=live.owner(s.get("owner")))
             for s in (shown.get("steps") or ())]
    condition, where = live.condition(shown)
    out = dict(shown, steps=steps, condition=condition, worktree=where)
    # The agents that actually MOVED this plan — the `by` of every tick and skip — which is
    # the same join both stats want and is read once for the two of them.
    who = [c["by"] for c in _closings(out).values() if c.get("by")]
    if (found := live.roles(who)):
        out["roles"] = found
    if tokens and (spent := live.tokens(who)):
        out["tokens"] = spent
    return out


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
            f"{_units(p):<10}{cond}{where}"
            f"{_flat(p.get('display') or p.get('title') or '(untitled)')}")


def _is_record(p: dict) -> bool:
    """A change-record document — landing facts with no plan. `kind` absent means plan.

    The one discriminator between the two documents this store holds. A record carries a
    fixed execution+landing skeleton (`_skeleton`) rather than a hand-shaped step graph;
    everything else — storage, ids, locking, migration, the changelog, and the step
    rendering — is shared, which is the whole reason the record lives here rather than in a
    store of its own.
    """
    return p.get("kind") == KIND_RECORD


def _tier(p: dict) -> str:
    """A document's change tier — `direct` or `shaped` — for the board and `list` tag.

    Read from `change.path`, the tier's own field, and NOT from `kind`: the path is where the
    design says the tier lives. It agrees with the kind today (a record is direct, a plan is
    shaped), but a document whose `change` is missing or hand-mangled still gets an honest
    answer from the kind rather than a blank. The tag matters precisely because a record now
    draws a step chart like a plan's, so the two are no longer told apart by having a chart or
    not — the word is what restores the distinction at a glance.
    """
    c = p.get("change")
    path = c.get("path") if isinstance(c, dict) else None
    if path in (DIRECT, SHAPED):
        return path
    return DIRECT if _is_record(p) else SHAPED


# The change-record fields that are landing FACTS, as against `path`/`phase`, which a record
# is born with. A plan's record is drawn only once one of these lands, so a fresh shaped plan
# reads exactly as it did before the record existed; a record document draws its section
# always, the record being the whole of what it is.
_CHANGE_FACTS = ("request", "contract", "cause", "solution", "scope", "verification",
                 "review", "limitations", "baseline", "human_checks", "pr", "approval",
                 "landing", "handoff")


def _change_told(p: dict) -> bool:
    """Is there a change record worth drawing here? A record document always is."""
    c = p.get("change")
    if not isinstance(c, dict):
        return False
    return _is_record(p) or any(_some(c.get(k)) for k in _CHANGE_FACTS)


def _units(p: dict) -> str:
    """What `list` says in the column a plan uses for its step count.

    A record now carries a step skeleton like a plan, so the bare word `record` no longer
    tells the two apart — the TIER does. A record shows its tier word (`direct`); a plan shows
    its step count, a number that already reads as the shaped side of the pair.
    """
    return _tier(p) if _is_record(p) else _count(p.get("steps") or [])


def _change_defects(plan: dict) -> list[str]:
    """What the lifecycle VALIDATES about a change record, as warnings and never refusals.

    The phases are advisory — a lead writes `phase` by hand and the agent is its interpreter
    — so this does NOT police what work happened when: the guide says plainly that running a
    step ahead of its deps is allowed, and nothing here second-guesses that scheduling. What
    it validates is narrower and is the one thing the design is firm about: a record must not
    PRESENT ITSELF AS SANCTIONED before it was. So the checks are on the record's own claims,
    read against `_PHASES`, and each is drawn red like any other defect and refuses nothing.

    - `execution` or later without both parts of the combined approval identity is
      implementation presented as sanctioned without identifying what was approved — the one
      lifecycle rule the Phase 3 contract states outright. Shaped only: a direct change has
      no approval and never claims one.
    - `landing` or later with no PR recorded is a change landing before it is on a pull
      request, which is an order the lifecycle cannot have.

    A phase the lifecycle does not have is not a defect — it is a job's own word, exactly as
    an unknown `progress` is — so an unrecognised phase is simply not checked here.
    """
    c = plan.get("change")
    if not isinstance(c, dict):
        return []
    phase = c.get("phase")
    if phase not in _PHASES:
        return []
    pi = _PHASES.index(phase)
    out: list[str] = []
    if c.get("path") == SHAPED and pi >= _PHASES.index("execution"):
        approval = c.get("approval")
        missing = [key for key in ("plan_revision", "contract_digest")
                   if not isinstance(approval, dict) or not _some(approval.get(key))]
        if missing:
            out.append(f"phase is '{_flat(phase)}', at or past execution, but the combined "
                       f"change approval (`change.approval`) has no "
                       f"{' or '.join(f'`{key}`' for key in missing)} — implementation is "
                       f"presented as sanctioned without the complete approval identity. "
                       f"Record that identity, or move the phase back to `approval`.")
    if pi >= _PHASES.index("landing") and not _some(c.get("pr")):
        out.append(f"phase is '{_flat(phase)}', at or past landing, but no PR is recorded "
                   f"(`change.pr`) — a change cannot be landing before it is on a pull "
                   f"request. Record the PR, or move the phase back.")
    return out


def _change_section(p: dict) -> list[str]:
    """The change record as `show` draws it: path, phase, and every landing fact present.

    Empty for a plan whose record holds nothing yet, so a fresh shaped plan reads as it did
    before Phase 3; always drawn for a record document. The structured facts render through
    the same small nested view `strategy` uses; the scalar ones render as their own lines,
    block text line by line. Defensive about a hand-mangled `change`: a wrong record costs
    this one section rather than the file, exactly as a bare checkpoint or note does.
    """
    c = p.get("change")
    if not isinstance(c, dict) or not _change_told(p):
        return []
    path = _flat(c["path"]) if _some(c.get("path")) else "—"
    if _some(c.get("phase")):
        path += f" · {_flat(c['phase'])}"
    out = ["change", f"  path      {path}"]
    for key in ("request", "cause", "solution", "scope", "contract"):
        if _some(c.get(key)):
            lines = _lines(c[key])
            out.append(f"  {key:<9} {lines[0]}")
            out.extend(f"            {ln}" for ln in lines[1:])
    for key in ("approval", "verification", "review", "limitations", "baseline",
                "human_checks", "pr", "landing", "handoff"):
        if _some(c.get(key)):
            out.append(f"  {key}")
            out.extend(f"    {ln}" for ln in _strategy_lines(c[key]))
    return out


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
    lines = [f"{p['id']}  {_flat(p.get('display') or p.get('title') or '(untitled)')}"]
    if p.get("display"):
        # The title is what the job is and this is what the BOARD draws instead of it, so
        # an author reading a plan back can see the header a glance will actually get.
        lines.append(f"  board       {_flat(p['display'])}")
    lines += [f"  workspace   {_where(p)}",
              f"  checkout    {_flat(p.get('checkout') or '—')}"]
    if p.get("planner"):
        # WHO MAY RESHAPE THIS PLAN, on the plan and not buried in `--json`: with a planner
        # the shape belongs to that agent instead of to the worktree's owner, and an agent
        # about to edit a step's deps is exactly who has to be told. Drawn only when it is
        # there, like the condition above — a plan with no planner is the ordinary case and
        # has nothing to say about one.
        lines.append(f"  planner     {_flat(p['planner'])} — the plan's shape is theirs")
    if p.get("condition"):
        lines.append(f"  condition   {_condition(p)}")
    lines.append(f"  created     {_when(p.get('created_at'))} "
                 f"by {_flat(p.get('created_by') or '—')}")
    steps = p.get("steps") or []
    # Drawn whenever there are steps, whichever kind of document — a direct change's skeleton
    # renders here exactly as `show --markdown` renders it, so the terminal and the PR agree.
    # A plan with no steps still says so; a legacy stepless record simply has nothing to draw
    # here and leans on its change section below.
    if steps or not _is_record(p):
        lines.append("")
        lines.extend([f"  {s}" for s in (_step_lines(steps) or ["(no steps yet)"])])
    change = _change_section(p)
    if change:
        lines.append("")
        lines.extend(f"  {ln}" for ln in change)
    if p.get("notes"):
        lines.append("")
        lines.append("  notes")
        lines.extend(f"    {_flat(n.get('text'))}  ({_flat(n.get('by') or '—')}, "
                     f"{_when(n.get('at'))})"
                     for n in (_rec(x, "text") for x in p["notes"]))
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
                    "checkpoints", "command", "root", "anchor", "strategy"})


def _strategy_lines(value: Any, indent: int = 0) -> list[str]:
    """A small nested terminal view of strategy; JSON remains the lossless rendering."""
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return [f"{pad}{{}}"]
        out = []
        for key, child in value.items():
            label = _flat(key)
            if isinstance(child, (dict, list)):
                out.append(f"{pad}{label}")
                out.extend(_strategy_lines(child, indent + 1))
            else:
                out.append(f"{pad}{label}  {_flat(child)}")
        return out
    if isinstance(value, list):
        if not value:
            return [f"{pad}[]"]
        out = []
        for child in value:
            if isinstance(child, (dict, list)):
                out.append(f"{pad}-")
                out.extend(_strategy_lines(child, indent + 1))
            else:
                out.append(f"{pad}- {_flat(child)}")
        return out
    return [f"{pad}{_flat(value)}"]


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
        # `progress` is an open vocabulary, so a value can be longer than its column;
        # `_col` keeps a gap either way, where a bare `:<10` glued `waiting on Andrew`
        # straight onto the step name beside it.
        bits = [f"{_flat(s.get('id', '?')):<9}{_col(_flat(s.get('progress', '?')), 10)}"
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
        if "strategy" in s:
            out.append("    strategy")
            out.extend(f"      {line}" for line in _strategy_lines(s["strategy"]))
        out.extend(f"    ref   {_flat(c.get('ref'))}"
                   for c in (_rec(x, "ref") for x in (s.get("checkpoints") or ())))
        out.extend(f"    note  {_flat(n.get('text'))}  ({_flat(n.get('by') or '—')}, "
                   f"{_when(n.get('at'))})"
                   for n in (_rec(x, "text") for x in (s.get("notes") or ())))
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


# Machinery the code needs and a human-facing markdown rendering does not. `anchor` is
# resolved onto a step for `_wrong`; `pr_comment_nonce` is persisted on a plan so a retry
# can recover the same external identity. Both remain in `--json`, the machine rendering.
#
# Kept out of markdown by dropping these fields from the copy being dumped (`_dumped`),
# one call above it. The underlying record and `--json` remain untouched.
_MACHINERY = frozenset({"anchor", "pr_comment_nonce", "kind"})


def _dumped(shown: dict) -> dict:
    """A resolved plan with the machinery taken back out, for the rendering a HUMAN reads.

    `show --markdown` is what `create-pr` posts onto the pull request, so what is in it is
    what whoever turns up reads. `anchor: pr` under a step and a plan's external-comment
    nonce are operational details, not facts about the job. Dropped from the copy rather
    than skipped by the renderer: see `_MACHINERY`. A copy, so `data` is untouched and
    `--json` still means what it meant.
    """
    return dict({k: v for k, v in shown.items() if k not in _MACHINERY},
                steps=[{k: v for k, v in s.items() if k not in _MACHINERY}
                       for s in (shown.get("steps") or ())])


# -- the plan as markdown ------------------------------------------------------
#
# WALKED, THEN TEMPLATED ON TOP. What is below is a walk: `_full` above is the terminal
# rendering and knows every field by name, and this deliberately does not — a rendering
# with the schema written into it stops being true the week a field is added and raises the
# week one is dropped, in front of somebody's merge, from a step that is only supposed to
# be reporting. So it walks the record: a new field appears on its own, a removed one
# vanishes, and neither costs an edit here.
#
# The WHOLE-PLAN markdown — the pull request comment — is a template over that walk, and
# lives further down under `_comment`. It draws the fields a human reads by name and hands
# every other field, known or not, back to this walk inside a collapsed metadata block, so
# the property above is kept and the comment is still something somebody can take in at a
# glance. `show <step> --markdown` is the walk alone. See `_markdown`.
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
# In the WALK, every line of a dump is BLOCKQUOTED, which is what keeps the forged-row
# property the rest of this file holds by escaping: no line inside a quote can start a step
# row or a markdown table row, however it is spelled. In the pull request COMMENT the same
# property is kept a different way — the block is lifted out of the step's own fold into a
# contract section of its own and rendered as the markdown it was written as, so it can draw
# a heading or a table inside its own section and cannot forge a row of any step's. See
# `_outputs`.

# The short spelling of an id, as a WHOLE value. See `_readable`.
_LONG = re.compile(r"^(p|s)-(\d+)$", re.IGNORECASE)


def _markdown(p: dict) -> str:
    """One plan as markdown — or, for a single step, the walk that was here before it.

    TWO CALLERS AND TWO RENDERINGS, and the branch is the shape of what it was handed.
    `_plan_result` passes a whole plan and that is the pull-request comment: a bespoke
    template (`_comment`), because that comment is close to the whole of what a human ever
    sees of a plan and the walk below made a wall of quoted text out of it. `_one_step`
    passes ONE step, which has no `steps` list, and that keeps the walk — it is read in a
    terminal by whoever is working the step, it has no graph to draw and no rows to line
    up, and the walk is what stops a new field going missing there.

    A DOCUMENT is a plan (a `steps` list, even empty) or a change record (a `change` object);
    both render human-first through `_comment`. A single step is neither — `_one_step` passes
    one step dict — and takes the walk. `kind` cannot be the discriminator here: `_dumped`
    strips it before this is reached, so the shape a document actually has on the copy — a
    `steps` list or a `change` — is what decides. Something that is not a dict where a step
    should be falls back to the walk rather than failing, like the schema facts below it.
    """
    steps = p.get("steps")
    steps_ok = isinstance(steps, list) and all(isinstance(s, dict) for s in steps)
    # A non-empty steps list with a non-dict in it is CORRUPTION, and it falls to the walk
    # even when a `change` record is present. The human-first path would render such a
    # document with an empty steps list and silently drop the legitimate steps beside the
    # bad one; the walk shows everything, which is the fallback this function promises
    # everywhere else and the reason a malformed record costs a rendering rather than a step.
    malformed = isinstance(steps, list) and steps and not steps_ok
    if not malformed and (steps_ok or isinstance(p.get("change"), dict)):
        return _comment(p, steps if steps_ok else [])
    return _markdown_walk(p)


def _markdown_walk(p: dict) -> str:
    """The generic walk: a heading, its scalar fields, then a section per collection."""
    used = next((k for k in _HEADS if _some(p.get(k))), None)
    return "\n".join(["# " + _heading(p, used)]
                     + _walked(p, {"id"} | ({used} if used else set())))


def _heading(p: dict, used: Optional[str]) -> str:
    """What names the plan on its first line: the id, then whichever of `_HEADS` is there."""
    head = " — ".join(x for x in (_cell("id", p.get("id")) if _some(p.get("id")) else "",
                                  _cell(used, p[used]) if used else "") if x)
    return head or "plan"


def _walked(p: dict, skip: set, level: int = 2) -> list[str]:
    """Everything under a heading, walked. Empty in, empty out — nothing is drawn blank.

    `level` is how deep the section headings sit, because this is used twice now: at the
    top of the walk, where a section is a `##`, and inside the comment's collapsed
    metadata, where the same sections hang under a block that is already a section itself.
    """
    lines: list[str] = []
    rows = {k: v for k, v in p.items() if k not in skip and _scalar(v) and _some(v)}
    if rows:
        lines += ["", "| field | value |", "| --- | --- |"]
        lines += [f"| {_title(k)} | {_cell(k, v)} |" for k, v in rows.items()]
    for k, v in p.items():
        if k in skip or _scalar(v) or not _some(v):
            continue
        lines += ["", "#" * level + f" {_title(k)}", ""]
        lines += _table(v) if _tabular(v) else _bullets(v)
    return lines


# -- the pull request comment --------------------------------------------------
#
# TEMPLATED, AND THE ONLY THING HERE THAT IS. Everything above walks; this reads the
# schema by name — the one place in this file where that is the right trade, because of
# who reads it. `create-pr` posts this onto the pull request and `merge` rewrites it, so
# for most plans it is ALL a human ever sees of the plan, and a rendering that is merely
# correct about a schema is not the same as one somebody can take in at a glance. The walk
# put internal plumbing in the same table as the work, and — because `output` is a block —
# degraded the steps from a table into bullets with a wall of blockquoted contract under
# them, exactly when a plan had the most to say.
#
# WHAT IS OPEN AND WHAT IS FOLDED is the layout's whole argument, and it is stated in full
# on `_comment`. Four things open at the top — the status and totals, the graph, the
# contract, the gates — and then one collapsed `<details>` per step. Nothing here is a
# table of steps any more: the fields that would have been its columns are the collapsed
# title (`_fold_title`) and the first rows of the body (`_fold_body`).
#
# WHAT THE WALK BOUGHT IS KEPT ANYWAY, and it is worth saying how, because "bespoke" would
# otherwise mean "a field added next month is invisible in front of somebody's merge". The
# template names the fields it draws (`_SHOWN_PLAN`, `_SHOWN_STEP`) and hands EVERYTHING
# ELSE — plan keys and step keys alike, known or not — to the same walk. A plan's undrawn
# fields go to the collapsed metadata block at the bottom; a STEP's go inside that step's
# own fold, under the step they are about. So a field this file has never heard of still
# arrives on the PR on its own, a field that goes away vanishes, and neither costs an edit
# here. What changed is where such a field lands: below a fold rather than beside the work.
#
# THE FORGED ROW, which every renderer in this file is arranged against. Each SCALAR still
# goes through `_cell` and so through `_flat`, so a newline stored in a name or an owner is
# the `\n` it is and starts no row. The one exception is deliberate and is the whole point
# of the field: a step's `output` is a human-authored markdown block — an approved change
# contract, a review — and it renders as the markdown it was written as, in the contract
# section at the top and OUT of every step's fold entirely. It can therefore draw a heading
# or a table of its own inside that section, and that is what it is for; what it cannot do
# is forge a row of a step's own table, because it is in no such table at all.

_SHOWN_PLAN = frozenset({"id", "display", "title", "steps", "incomplete",
                         # Put on the copy by `_viewed` and drawn by name above: the token
                         # total on its own line, and `roles` inside each step's fold. Named
                         # here so neither also lands in the metadata block below the fold —
                         # `roles` especially, which is a lookup table and not a reading.
                         "tokens", "roles",
                         # The change record is drawn by the human-first sections — the
                         # `_need_section`/`_why_section`/`_evidence_section` on the pull
                         # request, `_change_section` in the terminal — not walked into the
                         # metadata block, and `kind` is machinery the dump strips. Named
                         # here so neither lands in the metadata fold.
                         "change", "kind"})
_SHOWN_STEP = frozenset({"id", "name", "display", "progress", "why", "gate", "output",
                         "owner", "deps", "obliged_by", "root"})

# A value as something a mermaid node id or a markdown anchor can be spelled with.
_UNSAFE = re.compile(r"[^0-9A-Za-z]+")


def _comment(p: dict, steps: list) -> str:
    """A plan or a change record as the comment that goes on the pull request, HUMAN-FIRST.

    THE FIRST SCREENFUL IS FOR ANDREW, and that is the whole of the order. A pull request is
    read by a person deciding what THEY still have to do and whether the change is safe to
    land, so the comment opens with exactly that, in four sections and in this order:

      1. What you need to do    the human-only checks and the open gates — or, in as many
                                words, that there are none. Nothing else is above it.
      2. What changed and why   the root cause or feature intent and the selected solution,
                                read from the change record. A summary, not the diff.
      3. Agent evidence         the reviewed commit, the verification, the independent review
                                and its fixes — the case that the change is sound.
      4. Detailed record        everything else, COLLAPSED: the shaped plan with its graph,
                                its per-step folds, the full contract, and the observability
                                detail. Present when there is a plan; a direct change has no
                                plan and this is just its record's own leftovers.

    The change record is where the first three sections read from, which is what lets a
    DIRECT change — no plan, no steps — render the same shape as a shaped one without an
    empty or invented plan under it. The detailed record keeps the whole of the old
    rendering, so nothing a human could want is gone; it is one click away rather than the
    first thing in the way.
    """
    used = next((k for k in _HEADS if _some(p.get(k))), None)
    lines = ["# " + _heading(p, used)]
    # The title under the heading when the display took the heading: they are two
    # different sentences on purpose, and the long one is the one that says what the job is.
    if used == "display" and _some(p.get("title")):
        lines += ["", f"_{_cell('title', p['title'])}_"]
    lines += _need_section(p, steps)
    lines += _why_section(p)
    lines += _evidence_section(p)
    lines += _detail_record(p, steps)
    return "\n".join(lines)


def _change_of(p: dict) -> dict:
    """The change record on a document, or an empty one — read defensively, never refused."""
    c = p.get("change")
    return c if isinstance(c, dict) else {}


# WHAT §1 SAYS WHEN THERE IS NOTHING IN IT, and why that is two sentences rather than one.
# "Nothing for you" is the single most consequential line in this comment — it is the one a
# person acts on by closing the tab — so it may only be said where somebody actually said
# it. An ANSWERED change is one whose record carries `human_checks` — the list, or the `none`
# sentinel — which is `create-pr`'s job to write before the PR opens: a person's work was
# considered and the answer, if that is what it is, was none. A record carrying nothing there
# has not been asked yet — a legacy plan from before the change record existed, or a comment
# somehow posted before the list was written — and saying "agent verification covers this"
# there is the record claiming an assurance nobody gave.
_NO_HUMAN_WORK = "Nothing—agent verification covers this change."
_NO_HUMAN_ANSWER = ("Not recorded — nobody has written down what a human still has to "
                    "check, so this is unanswered rather than empty.")


def _need_section(p: dict, steps: list) -> list[str]:
    """`## What you need to do` — the human-only checks and the open gates, or that none remain.

    Always drawn, because the one thing a person must not have to hunt for is whether the
    change is waiting on them. Empty is itself the answer, said outright — but only where the
    record answered it; see `_NO_HUMAN_ANSWER` above for the case where nobody has. The checks
    are the change record's `human_checks`, written by `create-pr` before the PR opens; the
    open gates (below) are read off the steps.
    """
    c = _change_of(p)
    checks = c.get("human_checks")
    answered = _some(checks)
    # `none` is the sentinel a change with nothing for a human writes into `human_checks`;
    # it means the same as an empty list, and it renders as the sentence below, not the word.
    if isinstance(checks, str) and checks.strip().lower() == "none":
        checks = None
    body: list[str] = []
    if _some(checks):
        if isinstance(checks, list):
            # TICKABLE, so a human reading the PR on a phone runs the list by ticking it —
            # GitHub renders `- [ ]` as a checkbox where a plain `-` is an inert bullet, and
            # a manual-verification list is the one thing on this comment a person acts on
            # item by item. (State does not persist across a comment refresh — the body is
            # regenerated each time — so this is a legible checklist, not a saved one.)
            body += [f"- [ ] {_flat(x)}" for x in checks]
        else:
            body += _lines(checks)      # a markdown block, rendered as itself
    # Open gates are the other thing a human still owes, and they tick the same way.
    body += [f"- [ ] **{_cell('id', s.get('id'))}** — {_cell('gate', s['gate'])}"
             for s in (steps or ())
             if _some(s.get("gate")) and s.get("progress") not in (DONE, SKIPPED)]
    if not body:
        body = [_NO_HUMAN_WORK if answered else _NO_HUMAN_ANSWER]
    return ["", "## What you need to do", ""] + body


def _why_section(p: dict) -> list[str]:
    """`## What changed and why` — the root cause/intent and the selected solution.

    A summary read from the change record, not the contract in full — the full contract is a
    click away in the detailed record. Omitted when the record carries none of it, rather
    than drawn empty: a legacy plan that never filled its record has nothing to summarise
    here, and its contract is still under the fold.
    """
    c = _change_of(p)
    rows = [(label, c[key]) for key, label in
            (("request", "Request"), ("cause", "Root cause / intent"),
             ("solution", "Selected solution"), ("scope", "Scope boundaries"))
            if _some(c.get(key))]
    if not rows:
        return []
    lines = ["", "## What changed and why", ""]
    for label, val in rows:
        vlines = _lines(val)
        lines.append(f"- **{label}:** {vlines[0] if vlines else ''}")
        lines += [f"  {x}" for x in vlines[1:]]
    return lines


def _evidence_section(p: dict) -> list[str]:
    """`## Agent evidence` — the reviewed commit, the verification, the review and its fixes.

    The case that the change is sound, bound to the identities the change record carries so a
    reader sees what was verified and reviewed rather than a claim that it was. Omitted when
    the record carries no evidence.
    """
    c = _change_of(p)
    rev = c.get("review") if isinstance(c.get("review"), dict) else {}
    ver = c.get("verification") if isinstance(c.get("verification"), dict) else {}
    parts: list[tuple[str, Any]] = []
    commit = rev.get("commit") or ver.get("commit")
    if _some(commit):
        parts.append(("Reviewed commit", commit))
    # `verification` carries its own `environment`, and `review` its `fixes`, so both render
    # under their section without a field of their own. `limitations` and `baseline` are
    # optional and absent unless used (like `handoff`): a known limitation, and an evidenced
    # pre-existing failure the change did not cause.
    for key, label in (("verification", "Verification"), ("review", "Independent review"),
                       ("limitations", "Known limitations"),
                       ("baseline", "Baseline failures")):
        if _some(c.get(key)):
            parts.append((label, c[key]))
    if not parts:
        return []
    lines = ["", "## Agent evidence", ""]
    for label, val in parts:
        if _scalar(val):
            lines.append(f"- **{label}:** {_cell(label.lower(), val)}")
        else:
            lines.append(f"- **{label}:**")
            lines += [f"  {x}" for x in _bullets(val, depth=1)]
    return lines


# The change-record keys the first three sections DRAW. Everything else on the record is
# preserved by `_change_remainder` below, so the split is stated once here rather than kept in
# step with three functions by hand. `human_checks` is §1; `request`/`cause`/`solution`/`scope`
# are §2; the evidence keys are §3. What is left — the approved `contract`, the `approval`
# identity, the `pr` head, the `landing` approval and outcome, an optional `handoff`, `path`,
# `phase`, and any field a later author adds — is the remainder, and it MUST render somewhere
# or a direct PR would silently drop half its record (`_metadata` cannot draw it: `change` is
# in `_SHOWN_PLAN`, so the walk skips it).
_CHANGE_PROMOTED = frozenset({"request", "cause", "solution", "scope",
                              "verification", "review", "human_checks",
                              "limitations", "baseline"})


def _change_remainder(p: dict, steps: list) -> list[str]:
    """The change-record fields the first three sections did not draw, collapsed, once.

    The record is the point of a direct change and half of a shaped one, and the human-first
    sections lift only what belongs in the first screenful. The rest — the approved contract,
    the approval identity, the PR head, the landing approval and outcome, the optional handoff,
    and anything a later author adds — is still the record and must not vanish, so it renders
    here in a collapsed block. Promoted content is not repeated (`_CHANGE_PROMOTED`), and a
    block string like the contract renders as the markdown it is rather than one escaped row;
    everything else walks, so a field this file has never heard of still lands.
    """
    c = _change_of(p)
    rest = {k: v for k, v in c.items() if k not in _CHANGE_PROMOTED and _some(v)}
    # A shaped approval mirrors the approved contract into both `change.contract` and the
    # change-approval step's output. `_outputs` already preserves the step output above this
    # block, so an exact mirror is one fact and renders once.
    if "contract" in rest and any(s.get("output") == rest["contract"] for s in steps):
        rest.pop("contract")
    if not rest:
        return []
    blocks = {k: v for k, v in rest.items() if isinstance(v, str) and "\n" in v}
    walk = {k: v for k, v in rest.items() if k not in blocks}
    lines = ["", "<details>", "<summary>change record</summary>", ""] + _walked(walk, set(),
                                                                                level=4)
    for k, v in blocks.items():
        lines += ["", "#### " + _title(k), ""] + _lines(v)
    return lines + ["", "</details>"]


def _detail_record(p: dict, steps: list) -> list[str]:
    """`## Detailed record` — everything else, collapsed: the shaped plan, and the record's rest.

    The whole of the rendering that used to be the comment, moved under one fold so nothing a
    human could want is gone — only out of the first screenful. A plan brings its status, its
    graph, the full contract, the per-step folds and the metadata; both a plan and a direct
    change bring the CHANGE-RECORD REMAINDER — the record fields the first three sections did
    not draw — so nothing on the record is silently dropped. Drawn only when there is something
    under it to draw.
    """
    inner: list[str] = []
    if steps:
        inner += [_status(steps)]
        if (span := _elapsed(p)):
            inner += ["", span]
        if (spend := _tokens(p)):
            inner += ["", spend]
        inner += _defect_lines(p)
        inner += ["", "## how it runs", ""] + _graph(steps)
        inner += _outputs(steps)
        inner += _gates(steps)
        inner += ["", "## steps"] + _folds(p, steps)
        inner += _change_remainder(p, steps)
        inner += _metadata(p)
    else:
        if (span := _elapsed(p)):
            inner += [span]
        inner += _defect_lines(p)
        inner += _change_remainder(p, steps)
        inner += _metadata(p)
    if not any(str(x).strip() for x in inner):
        return []
    return (["", "## Detailed record", "", "<details>", "<summary>the full record</summary>",
             ""] + inner + ["", "</details>"])


def _status(steps: list) -> str:
    """The one line at the top, read off the steps and nothing else.

    `progress` is an OPEN vocabulary — `done` and `skipped` are what the verbs write and a
    hand-edited plan may say anything — so the three are counted by name and whatever else
    is there is NAMED rather than folded into "open". A status line that swallowed a
    `waiting on Andrew` into a count would be hiding the one word somebody wrote by hand.
    """
    done = [s for s in steps if s.get("progress") == DONE]
    skipped = [s for s in steps if s.get("progress") == SKIPPED]
    rest = [s for s in steps if s.get("progress") not in (DONE, SKIPPED)]
    word = "finished" if not rest else ("not started" if not (done or skipped)
                                        else "in progress")
    bits = [word, f"{len(done)}/{len(steps)} done"]
    if skipped:
        bits.append(f"{len(skipped)} skipped")
    odd = sorted({_flat(s["progress"]) for s in rest
                  if _some(s.get("progress")) and s.get("progress") != OPEN})
    bits += odd
    if (gate := _at_gate(steps, rest)):
        bits.append(gate)
    return "**Status:** " + " · ".join(bits)


def _at_gate(steps: list, rest: list) -> str:
    """Which human gate the plan is sitting at, if it is sitting at one.

    "Blocked at" only when everything the gated step waits for is settled — a gate five
    steps out is something to know about and is not what is holding the plan up, and a
    status line that called both the same would cry wolf on every plan that has a merge.
    """
    settled = {s.get("id") for s in steps if s.get("progress") in (DONE, SKIPPED)}
    gated = [s for s in rest if _some(s.get("gate"))]
    if not gated:
        return ""
    ready = [s for s in gated if all(d in settled for d in (s.get("deps") or ()))]
    at = (ready or gated)[0]
    name = _flat(at.get("display") or at.get("name") or at.get("id") or "a step")
    return f"blocked at the {name} gate" if ready else f"{name} gate ahead"


def _elapsed(p: dict) -> str:
    """How long the job has been running, off `created_at` and the changelog's last entry.

    Both are on the record `show` already has, so this needs no store and no new field.
    Nothing is claimed when there is nothing to read it off: a hand-written plan with no
    timestamps gets no line rather than a zero.
    """
    marks = [t for t in [p.get("created_at")]
             + [e.get("at") for e in (p.get("changelog") or ()) if isinstance(e, dict)]
             if isinstance(t, int) and not isinstance(t, bool) and t]
    if not marks:
        return ""
    first, last = min(marks), max(marks)
    return (f"**Elapsed:** {_span(last - first)} · started {_when(first)} · "
            f"last change {_when(last)}")


def _span(secs: int) -> str:
    """A duration a human reads, at one unit of precision below the one that dominates."""
    if secs < 60:
        return "under a minute"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 172800:
        return f"{secs // 3600}h {(secs % 3600) // 60}m"
    return f"{secs // 86400}d {(secs % 86400) // 3600}h"


def _closings(p: dict) -> dict:
    """Every step's LAST closing changelog entry, keyed by step id — `{at, by}`.

    The changelog is the only place a step's timing exists. Nothing stamps a step when it
    is picked up; `tick` and `skip` are the two verbs that stamp one when it is let go
    (`_on_step`, `CLOSING`). So "when was this finished" and "who finished it" are read off
    the entry that finished it and off nothing else, which is why the two stats below need
    no new field, no migration and no store.

    THE LAST entry and not the first: a re-entered step is ticked, reopened by hand and
    ticked again, and what a reader wants is when it was actually finished. The changelog
    is append-only, so later in the list is later in time.

    A step is named by the FIRST WORD of the entry's detail, which is how every verb here
    writes one (`_progress` returns `s-2 open -> done`). Matched against the ids actually in
    the plan rather than parsed as an id: `step-1` and `step-10` both start with `step-1`,
    and a prefix test would credit one step's tick to another, silently.
    """
    ids = {str(s.get("id")) for s in (p.get("steps") or ()) if _some(s.get("id"))}
    out: dict = {}
    for e in (p.get("changelog") or ()):
        if not isinstance(e, dict) or str(e.get("action") or "") not in CLOSING:
            continue
        at = e.get("at")
        if not (isinstance(at, int) and not isinstance(at, bool) and at):
            continue
        head = str(e.get("detail") or "").split(" ", 1)[0]
        if head in ids:
            out[head] = {"at": at, "by": str(e.get("by") or "")}
    return out


def _timings(p: dict, steps: list) -> dict:
    """How long each step took, keyed by step id: `(seconds, still running)`.

    `elapsed = done_at - unblocked_at`, where `unblocked_at` is the moment the step COULD
    have been started: the last of its deps to close, or the plan's own `created_at` for a
    root. Measuring from there is what takes dependency-blocked time back out — a step that
    sat behind two others for a day and then took ten minutes reads as ten minutes, which
    is the figure somebody looking for where a plan went is after.

    WHAT IS STILL IN IT, deliberately: gate-wait and pickup-idle. A step ready at midnight
    and picked up at nine reads as nine hours. Telling those apart needs a stamp at pickup,
    which is a schema change and a different job; the alternative here was no per-step
    figure at all, and end-to-end is the honest one of the two available.

    A dep that is not a step of this plan is IGNORED, which is the same answer `_graph`
    gives it: the record's defect is reported in words by `incomplete`, and refusing to time
    a step because of somebody's typo would hide a good figure behind a bad edge. A dep that
    IS here and has not closed means the step was never unblocked — there is nothing to
    measure from, so nothing is claimed.

    A still-open step gets a RUNNING figure, flagged so its cell can say so. A negative one
    — a hand-edited timestamp, a clock that went backwards — is dropped rather than drawn:
    a step that took minus two hours is not a fact about the job.
    """
    closed = _closings(p)
    here = {str(s.get("id")) for s in steps if _some(s.get("id"))}
    made = p.get("created_at")
    made = made if isinstance(made, int) and not isinstance(made, bool) and made else None
    now = int(time.time())
    out: dict = {}
    for s in steps:
        sid = str(s.get("id"))
        deps = [str(d) for d in (s.get("deps") or ()) if str(d) in here]
        if deps:
            if any(d not in closed for d in deps):
                continue                  # never unblocked: nothing to measure from
            start = max(closed[d]["at"] for d in deps)
        else:
            start = made
        if start is None:
            continue
        end = closed.get(sid, {}).get("at")
        if end is None:
            # SETTLED WITH NO STAMP: a step ticked or skipped by a hand-edit, which writes
            # no changelog entry at all. It is finished, so a running figure would be a lie
            # about a step nobody is working on — and there is no end to measure to, so
            # there is no figure. A step still OPEN is the other case and is genuinely
            # running, however long it has been.
            if str(s.get("progress") or "") in (DONE, SKIPPED):
                continue
        secs = (end if end is not None else now) - start
        if secs >= 0:
            out[sid] = (secs, end is None)
    return out


def _took(timings: dict, sid) -> str:
    """One step's elapsed, as the words that go in its cell.

    `_span` and not a second duration format: the plan-total line above the table already
    speaks in it, and two spellings of "an hour and four minutes" in one comment is exactly
    the kind of thing a reader stops to reconcile.
    """
    got = timings.get(str(sid))
    if not got:
        return ""
    secs, running = got
    return f"{_span(secs)} so far" if running else _span(secs)


def _did(closings: dict, roles: Any, sid) -> str:
    """Who moved this step past, as the ROLE where sb would say and the name where it would not.

    The role is the useful half — `worker`, `reviewer`, `qa` says what KIND of pass a step
    got, where an agent name is a topic somebody picked at spawn time. But sb only names the
    agents in the caller's own tree, and an agent closed weeks ago may be in neither, so the
    name is kept as the fallback: `by lead-pr-comment-stats` is worth strictly more than a
    blank cell, and it is a fact off the record rather than a guess off the store.
    """
    who = (closings.get(str(sid)) or {}).get("by") or ""
    if not who:
        return ""
    role = (roles or {}).get(who)
    return _flat(role) if role else _flat(who)


def _mag(n: int) -> str:
    """A count as a magnitude read at a glance: `900`, `12k`, `0.1m`, `1.2b`.

    The unit steps so the mantissa stays roughly in [0.1, 100), which is Andrew's spec and
    is the rule that keeps the figure the same WIDTH whatever the scale: a hundred thousand
    is `0.1m` rather than `100k`, and a plan that burned two billion tokens is still four
    characters. One decimal only below ten, because `12.3k` is precision nobody asked a
    summary line for.
    """
    if n < 1000:
        return str(n)
    for size, suffix in ((1_000_000_000, "b"), (1_000_000, "m"), (1000, "k")):
        if n / size >= 0.1:
            mant = n / size
            return ((f"{mant:.1f}".rstrip("0").rstrip(".") if mant < 10
                     else str(round(mant))) + suffix)
    return str(n)


def _tokens(p: dict) -> str:
    """The plan's total token spend, if it was readable — the line under the elapsed one.

    `tokens` is put on the COPY by `_viewed`, which is the one place the store and the
    transcripts can be reached; this reads a field and nothing else, so the renderer stays a
    pure function of the record it was handed and the tests can hand it one.

    NEVER A GUESS. The field is `{total, agents, seen}` when something was read and is
    absent when nothing was, so a plan whose transcripts could not be found gets no line
    rather than a zero — a zero reads as "this plan cost nothing", which is the one wrong
    answer available here. When only some of the agents answered, how many is said out
    loud: a partial total that looked complete would be worse than no total at all.
    """
    got = p.get("tokens")
    if not isinstance(got, dict) or not isinstance(got.get("total"), int):
        return ""
    seen, agents = got.get("seen"), got.get("agents")
    line = f"**Tokens:** {_mag(got['total'])}"
    if isinstance(seen, int) and isinstance(agents, int) and agents:
        line += (f" · across {agents} agents" if seen == agents else
                 f" · {seen} of {agents} agents read — the rest had no transcript to read")
    return line


def _node(sid) -> str:
    """A step id as a mermaid node id: prefixed, so it never opens with a digit."""
    return "n_" + _UNSAFE.sub("_", _flat(sid)).strip("_")


def _tag(sid) -> str:
    """A step id as the anchor its row carries and everything referring to it links to."""
    return _UNSAFE.sub("-", _cell("id", sid)).strip("-").lower()


def _graph(steps: list) -> list[str]:
    """The dependency graph as a mermaid `flowchart LR`, which GitHub draws natively.

    An edge is drawn only between two steps that are both HERE. A dep naming a step that
    is not in the plan is a defect the three doors report in words; a renderer that
    invented a node for it would draw a graph the plan does not have.
    """
    ids = {s.get("id") for s in steps}
    out = ["```mermaid", "flowchart LR"]
    out += [f'    {_node(s.get("id"))}["{_label(s)}"]' for s in steps]
    out += [f'    {_node(d)} --> {_node(s.get("id"))}'
            for s in steps for d in (s.get("deps") or ()) if d in ids]
    # Every step gets a class, so nothing falls through to mermaid's default fill — which
    # is the grey the legend spends on `skipped`, and a step still TO DO is not a skip. The
    # not-done states each get their own colour and each is named in the legend: `todo`
    # (blue, still to do), `skipped` (grey, deliberately not done), `gate` (amber, waits on
    # a person). Amber is the one that must stay unmistakable — it is the only state needing
    # a human — so `todo`'s blue is calm and does not compete with it.
    styled: dict = {"done": [], "todo": [], "skipped": [], "gate": []}
    for s in steps:
        which = (DONE if s.get("progress") == DONE else
                 SKIPPED if s.get("progress") == SKIPPED else
                 "gate" if _some(s.get("gate")) else "todo")
        styled[which].append(_node(s.get("id")))
    out += ["    classDef done fill:#dafbe1,stroke:#2da44e,color:#0a3622",
            "    classDef todo fill:#ddf4ff,stroke:#54aeff,color:#0a3069",
            "    classDef skipped fill:#eaeef2,stroke:#8c959f,color:#57606a",
            "    classDef gate fill:#fff8c5,stroke:#bf8700,color:#4d2d00"]
    out += [f"    class {','.join(nodes)} {name}"
            for name, nodes in styled.items() if nodes]
    return out + ["```", "",
                  "_green = done · blue = still to do · grey = skipped · "
                  "amber = waits on a human · "
                  "an arrow points from a step to what runs after it._"]


def _label(s: dict) -> str:
    """A node's text: the id and the short name, through `_flat` like every other value.

    The double quote is the one character a quoted mermaid label cannot hold, and it is
    spelled as the entity mermaid reads rather than dropped — a display name with a quoted
    phrase in it is ordinary, and a graph that failed to draw because of one would take the
    whole comment's diagram with it.
    """
    both = " · ".join(x for x in (_cell("id", s.get("id")) if _some(s.get("id")) else "",
                                  _flat(s.get("display") or s.get("name") or "")) if x)
    return (both or "step").replace('"', "#quot;")


def _outputs(steps: list) -> list[str]:
    """Every step's finished `output`, as the contract section — OPEN, near the top.

    RENDERED AS THE MARKDOWN IT IS — a change contract and a review are written as prose
    with nesting, and the walk's blockquote turned every one of them into a wall of quoted
    text. Kept out of the per-step folds so a block never has to fit inside one, and so the
    thing that was actually agreed is readable without opening anything.

    OPEN AND NOT FOLDED, which is the Phase-3 change to it. When a plan has a contract at
    all it is the single most-read thing on the comment — somebody arriving at the pull
    request is there to check the diff against it — and a fold is a click between them and
    the text. Most plans have no contract and get no section, so the cost of leaving it open
    is paid only by the plans where it is the point.

    Each block keeps its own `## <id> output` heading, which is the anchor the step's own
    fold links back to (`_head_of`, `_fragment`): the fold says a contract exists and where
    it is, and the text lives once, up here, rather than twice.
    """
    have = [s for s in steps
            if isinstance(s.get("output"), str) and _some(s["output"])]
    if not have:
        return []
    out: list[str] = ["", "## contract"]
    for s in have:
        out += ["", f"### {_head_of(s)}", ""] + _lines(s["output"])
    return out


def _head_of(s: dict) -> str:
    """The heading over a step's output, which is also what its row links to."""
    return f"{_cell('id', s.get('id')) or 'step'} output"


def _gates(steps: list) -> list[str]:
    """The human gates still ahead, in the words whoever wrote them wrote.

    Up top and OPEN rather than inside the gated step's own fold: a gate is a QUESTION for
    the person reading the pull request, and it is the one field on a plan addressed to them
    directly. A question behind a fold is a question that does not get answered.

    Last of the four open sections, because the three above it — where the job is, what
    shape it is, what was agreed — are what somebody needs to have read before the question
    means anything.
    """
    ahead = [s for s in steps
             if _some(s.get("gate")) and s.get("progress") not in (DONE, SKIPPED)]
    if not ahead:
        return []
    return ["", "## waiting on a human", ""] + [
        f"- **{_cell('id', s.get('id'))}** — {_cell('gate', s['gate'])}" for s in ahead]


def _defect_lines(p: dict) -> list[str]:
    """What `_plan_result` found incomplete, kept where somebody at a merge will see it."""
    if not _some(p.get("incomplete")):
        return []
    return ["", "## incomplete", ""] + [f"- {_flat(x)}" for x in p["incomplete"]]


def _folds(p: dict, steps: list) -> list[str]:
    """Every step as its own collapsed `<details>` — the title scans, the body explains.

    ONE FOLD PER STEP AND NO TABLE. See `_comment` for why the table went; what matters
    here is that a step's whole detail is now in one place, the place a reader opened
    because they wanted that step.

    `took` and `by` are read off the plan's changelog against the plan's dep graph
    (`_timings`, `_closings`) and neither is a field on a step, which is why this takes the
    whole plan: a step cannot be drawn from its own dict alone once a value depends on when
    its DEPS closed. `obliges` is the same edge as `obliged_by` read the other way round —
    the record says which step obliged this one, and what somebody reading a plan wants
    beside a step is what it drags in after it.

    THE BLANK LINES ARE LOAD-BEARING. One after `</summary>` and one before `</details>`,
    or GitHub renders the body as literal text rather than as the markdown it is — which is
    the same failure the contract section was written against, by another route.
    """
    timings, roles = _timings(p, steps), p.get("roles")
    closings = _closings(p)
    obliges: dict = {}
    for s in steps:
        if _some(s.get("obliged_by")):
            obliges.setdefault(s["obliged_by"], []).append(s.get("id"))
    here = {s.get("id") for s in steps}
    out: list[str] = []
    for s in steps:
        out += ["", "<details>", f"<summary>{_fold_title(s, timings)}</summary>", ""]
        out += _fold_body(s, closings, roles, obliges, here)
        out += ["", "</details>"]
    return out


def _fold_title(s: dict, timings: dict) -> str:
    """What stays visible when a step is folded: which step, what state, how long.

    `{id} · {display} — {name} | {state} | {elapsed}`, and the elapsed half is dropped
    WITH its separator when there is nothing to measure — a dangling `| ` at the end of
    every title on a plan that has not run yet is noise pretending to be a column. Cost
    would sit after it on the same rule and is deferred, so nothing renders it today.

    THE ID IS ON THE FRONT because everything else in the comment refers to a step by it:
    the graph's nodes, the gate list, the `after` and `obliges` cells inside another step's
    fold. A title without it would leave a reader who followed one of those links with no
    way of telling they had landed in the right place.

    PLAIN TEXT AND NO EMPHASIS. This is the content of an HTML `<summary>` element, and
    markdown inside one is at GitHub's discretion in a way markdown in a body is not; a
    title that rendered its own `**` is worse than a title with no bold in it. Every value
    still goes through `_cell`, so a newline stored in a name is the `\n` it is.
    """
    named = " · ".join(x for x in (_cell("id", s.get("id")) if _some(s.get("id")) else "",
                                   _named(s)) if x)
    bits = [named or "step", _state(s)]
    if (took := _took(timings, s.get("id"))):
        bits.append(took)
    return f'<a id="{_tag(s.get("id"))}"></a>' + " | ".join(bits)


def _fold_body(s: dict, closings: dict, roles: Any, obliges: dict,
               here: set) -> list[str]:
    """One step's whole detail: the fields drawn by name, then everything else, walked.

    THE WALK IS WHY THIS IS NOT JUST A TABLE. The fields below are named because a reader
    wants them in a fixed order; every OTHER field on the step — its notes, its checkpoints,
    its `tries`, and whatever a later author puts there — is handed to the same walk the
    rest of this file uses, right here under the step it belongs to. That is where they
    moved FROM the comment-wide metadata block: a note about step 3 was being filed at the
    bottom of the page next to the workspace path, which is filing rather than rendering.

    A scalar the walk turned up joins the same `field | value` table rather than starting a
    second one underneath it, because two tables in a row is a rendering artefact and not a
    distinction anybody reading it can act on.

    The contract is a LINK and not a copy: it is rendered once, open, at the top of the
    comment, and duplicating it inside the fold would put the same prose on the page twice
    and leave two things to keep in step.
    """
    sid = s.get("id")
    rows = [("after", _refs(s.get("deps"), here)),
            ("obliges", _refs(obliges.get(sid), here)),
            ("owner", _cell("owner", s.get("owner")) if _some(s.get("owner")) else ""),
            ("by", _did(closings, roles, sid)),
            # Only when it is TRUE. `root` is a claim that a step is a deliberate second
            # start, and the plans that carry it at all carry `false` on every other step —
            # a `root | no` row under all of them is a column of nothing, said out loud.
            ("root", _cell("root", True) if s.get("root") else ""),
            ("gate", _cell("gate", s["gate"]) if _some(s.get("gate")) else ""),
            ("output", f"[{_head_of(s)}](#{_fragment(_head_of(s))})"
                       if isinstance(s.get("output"), str) and _some(s["output"]) else "")]
    rest = {k: v for k, v in s.items() if _leftover(k, v)}
    got = [(k, v) for k, v in rows if v]
    got += [(_title(k), _cell(k, v)) for k, v in rest.items() if _scalar(v)]
    lines: list[str] = []
    if got:
        lines += ["| field | value |", "| --- | --- |"]
        lines += [f"| {k} | {v} |" for k, v in got]
    nested = {k: v for k, v in rest.items() if not _scalar(v)}
    if nested:
        lines += _walked(nested, set(), level=4)
    return lines


def _named(s: dict) -> str:
    """A step named for its fold title: the short name, and the whole sentence after it.

    BOTH, where they differ. `display` is what the board draws in a cell and is a display
    version of the sentence rather than an abbreviation of it — so the sentence is the part
    that actually says what the job is, and a comment that showed only the short one would
    leave whoever turns up at the pull request reading two words per step.

    No emphasis on either half: this goes inside a `<summary>`, where the `**` would be at
    risk of arriving as two asterisks. See `_fold_title`.
    """
    short = _cell("display", s.get("display")) if _some(s.get("display")) else ""
    full = _cell("name", s.get("name")) if _some(s.get("name")) else ""
    if short and full and short != full:
        return f"{short} — {full}"
    return short or full


def _fragment(heading: str) -> str:
    """A heading as the fragment GitHub gives it: lowercased, spaces for hyphens."""
    return _UNSAFE.sub("-", heading).strip("-").lower()


def _refs(ids, here: set) -> str:
    """A cell of step ids, each linking to that step's own row.

    An id naming a step that is NOT in the plan is drawn without the link, which is the
    same answer `_graph` gives when it draws no edge for one. Drawn, because the record
    says that edge is there and a rendering that hid it would hide the defect `incomplete`
    reports in words; not linked, because there is no row to land on. Shown and dead-ended
    is the only pair of those two that is honest.
    """
    return ", ".join(f"[{_cell('id', i)}](#{_tag(i)})" if i in here else _cell("id", i)
                     for i in (ids or ()))


def _state(s: dict) -> str:
    """The status cell: the progress word, whether the exit is a gate, and any reason."""
    bits = [_cell("progress", s.get("progress")) if _some(s.get("progress")) else OPEN]
    if _some(s.get("gate")):
        bits.append("gate")
    if _some(s.get("why")):
        bits.append(_cell("why", s["why"]))
    return " · ".join(bits)


def _leftover(k: str, v) -> bool:
    """Is this step field one the template did not draw, and so the walk's to draw?

    `output` is the one key that is sometimes both: the block section above renders it when
    it is a STRING, which is what it is whenever anything wrote it, and a hand-edited plan
    with a list or a number under that key falls back here rather than vanishing — the same
    fallback `_BLOCK` has had all along, kept on the other side of the split.
    """
    if not _some(v):
        return False
    return k not in _SHOWN_STEP or (k in _BLOCK and not isinstance(v, str))


def _metadata(p: dict) -> list[str]:
    """Everything about the PLAN that the template did not draw, walked, below the fold.

    This is half of where the walk's property is kept: a plan field this file has never
    heard of lands here on its own, without this function being told it exists, and the day
    one of them turns out to matter to a human it is promoted into the template above by
    name. Plumbing — the workspace, the checkout, the changelog — stays here for good, which
    is the other half of what the block is for.

    A STEP's undrawn fields are the other half and are no longer here: they render inside
    that step's own fold (`_fold_body`). Filing a note about step 3 at the bottom of the
    page beside the checkout path kept it visible and made it unfindable, and one fold per
    step is somewhere better to put it that did not exist before Phase 3.
    """
    rest = {k: v for k, v in p.items() if k not in _SHOWN_PLAN and _some(v)}
    if not rest:
        return []
    return (["", "<details>", "<summary>metadata</summary>"]
            + _walked(rest, set(), level=4) + ["", "</details>"])


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
    `change-approval` to its name in the library listing and a long workspace name to
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
