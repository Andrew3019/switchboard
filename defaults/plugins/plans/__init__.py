"""Plans and steps — the live state of one job, held where a lead can show it.

The design is `design/PLANS-AND-STEPS.md`; this is the state model, the verbs that make a
plan (`create`, `list`, `show`, `changelog`), the verbs that move one along — `assign`,
`tick`, `skip`, `note`, `checkpoint`, `rework`, `add-step` and `dep` — the catalogue a
plan is built from (`library`, `name-step` and `template`), the two things that are
READ every time a plan is displayed and written down nowhere — a step owner's status, and
the plan's own condition — and the instruction that says when to make a plan at all
(`guide`). What is still not here is anything that decides for itself: gates come later,
and they do not change the shape written below.

The records
-----------

    plan  {"id": "p-1", "workspace": "task-guardrails-build", "workspace_from": "agent",
           "checkout": "/…/worktrees/switchboard/task-guardrails-build", "title": "…",
           "steps": [...], "changelog": [...], "notes": [...],
           "created_by": "lead", "created_at": 1754570000}

    step  {"id": "s-1", "name": "…", "def": null, "obliged_by": null, "progress": "open",
           "why": null, "owner": null, "tries": 1, "notes": [], "deps": [],
           "checkpoints": []}

`progress` is an OPEN VOCABULARY, exactly as `todo`'s `state` is: `open` is what `create`
writes and `done`/`skipped` are what the lifecycle verbs will, but nothing here is an enum
and a lead that wants `progress: waiting on Andrew` gets it without a release. The design
says the agent is the interpreter and there is no schema to satisfy, so a step carrying a
field this file has never heard of is a feature and not corruption — `_step()` fills in the
fields the design names and leaves everything else alone.

Moving a step
-------------

Progress is moved by three verbs and only three: `tick` writes `done`, `skip` writes
`skipped`, and `rework` puts a step back to `open`. Nothing infers it, `sb done` does not
touch it, no verb moves it as a side effect of doing something else, and nothing in this
file ever writes `done` on a step's behalf — which is the design's first rule about progress
and the reason `tick` exists as a verb at all. Rework belongs on that list rather than
beside it: re-entering a step is a progress move like the other two, made by an agent that
typed the verb, and it is `open` it writes and never a completion.

Complete-or-skipped-but-never-both is structural rather than checked: `progress` is ONE
string, so `skip` on a ticked step replaces the tick instead of joining it. A verb that
overwrites what another verb wrote is a correction, and the changelog is what says which it
was — every one of these entries records the progress it moved a step FROM.

`why` is the reason for the step's current progress, kept on the step so that a skipped step
renders with the reason beside it rather than twenty lines below in the changelog. The
design's "a skip is a state rather than an absence" is only true if the reason is visible
where the state is. It is overwritten by whatever changes progress next, so a step ticked
after a skip does not keep the sentence explaining why it was skipped.

`tries` is rework: `rework` re-enters a step, bumping the count and putting progress back to
`open`. Repetition is a number on the step and never an edge, so nothing here creates a
cycle to represent a second attempt. Nothing downstream is un-ticked either — the design
makes that the lead's judgement, and a rule here would either merge unreviewed work or throw
away a day of good review.

`checkpoints` are references — a path, a URL, an id — and never content. A ref with a
newline in it is refused, because the only way one gets there is somebody pasting the brief
instead of pointing at it.

`deps` are what a step comes after: data the lead reads, and this file's only interest in
them is that they are storable and renderable. Nothing traverses them, waits on them,
orders anything by them or refuses a cycle in them — a join waits because the lead does not
start it. What IS checked is that an edge names a step that exists, in the same plan, and
not itself, since an edge to nothing is a typo rather than a shape.

Reassigning tells nobody. `assign` writes a name onto a step and stops there: the plan never
pushes to a running agent, and the old owner learns it lost the step from its parent or not
at all. Two agents believing they own one step is the collision the design accepts.

The catalogue
-------------

A step is either invented on the fly — `add-step`, `create --step`, a name and nothing else
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

A definition may COMPOSE — `{"steps": ["a", "b"]}` — and naming it puts a and b in the plan,
flat. What a plan holds is always flat: no step contains another, because a step that did
would be a plan by another name. Composition is the one edge in this file that is actually
traversed, which is why a cycle in it is REFUSED where a cycle in a plan's `deps` is not: a
`dep` nothing walks is a lead's mistake to read, and a composite that composes itself is a
hang. Expansion mints fresh ids from the same counter as everything else.

A definition may also OBLIGE another — `merge` obliges `merge-review` — and naming it adds
both. The obliged step carries `obliged_by`, the id of the step that brought it, and it can
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

Templates are `templates/*.json`: preconfigured plans, COPIED on use and never linked back.
`template list` browses them, because nobody knows at the start of a job that a template
exists for it — the lead looks once the work is shaped. A copy holds no reference to what it
came from and deleting the template file changes nothing about it. What a copy does carry is
the links: a named step inside a template stays a name, so it is still resolved live. Copies
and links are the two halves of this design and they point opposite ways on purpose.

Templates hold no `deps`. A template entry may expand into several steps, so an edge written
against an entry would have nothing single to attach to; edges are added with `dep` once the
copy exists. The catalogue is deliberately nearly empty — a merge, its review and one
template — because the design says what to promote into it is read off real runs rather than
decided up front, and the system has to work with it almost bare. It does: with no `library`
directory at all every verb here still works and only `name-step` has nothing to offer.

Ids are `p-<n>` and `s-<n>`, monotonic across the whole file and never reused, so a spawn
prompt or a changelog entry citing `s-7` stays true for the life of the repo. Step numbers
are minted from ONE counter rather than one per plan: two plans on a worktree would
otherwise both have an `s-1`, and a lead handing a worker "your step is s-1" would be
saying nothing. `next_plan`/`next_step` are stored, and recomputed as floors on read, so a
hand-deleted row cannot make the next create mint an id somebody already wrote down.

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
message; escaping at the render is what also covers a hand-edited `plans.json`, a name in
the library and the refusals themselves, none of which came through a verb. An id is the
sharpest of those: a refusal is what HAPPENS when an id fails to validate, so the message
is built out of the one value nothing has vetted.

The set is a property and not a list. What must not survive is anything `str.splitlines()`
will break a line on — which is C0 and the C1 range, and also U+2028 and U+2029, which no
"control character" range catches and which a test sweeps the whole codespace to pin.

The changelog
-------------

Append-only, written by the command, carrying the reason the agent supplied. That is the
whole record of how a job actually ran: a plan gets reshaped as it goes, and without this
the file keeps only the final shape. `_write` refuses a document whose changelog is shorter
than the one that was read, or whose existing entries have changed — so a bug in a future
verb that rewrites a plan wholesale fails loudly here instead of quietly losing the story.
It cannot stop somebody editing `plans.json` in an editor; nothing can, and the answer to
that is that every mutation goes through a command.

Storage is one JSON file, rewritten whole via tmp + `os.replace` under the lock sb already
holds around the handler. Whole-file rewrite is correct precisely because of that lock: a
command reads, changes the steps it names, and writes, with nothing able to interleave.
"""

from __future__ import annotations

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
LOCK = True

# The file, and the shape written into it. `format` is this plugin's own; sb neither reads
# it nor has an opinion about it.
FILE = "plans.json"
FORMAT = 1

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

# `p-1`, `P-1` and a bare `1` all name the same plan; likewise `s-1` for a step. An id is
# read out of a board or a spawn prompt and retyped, and being strict buys nothing.
_PLAN_ID = re.compile(r"^(?:p-)?(\d+)$", re.IGNORECASE)
_STEP_ID = re.compile(r"^(?:s-)?(\d+)$", re.IGNORECASE)

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
        help="how plan-making is done — when a plan exists, who makes it, what goes in it")
    reg.command(
        "create", create, audience="both",
        help="start a plan on this worktree, empty or with its steps already in it",
        args=[reg.arg("title", repeat=True, help="what this plan is for"),
              reg.arg("--step", repeat=True, help="a step to start with; repeat for more"),
              reg.arg("--note", repeat=True, help="a note on the plan; repeat for more"),
              reg.arg("--reason", help="why, for the changelog")])
    reg.command(
        "list", ls, audience="both", help="the plans on this worktree",
        args=[reg.arg("--all", flag=True, help="every plan, on every workspace")])
    reg.command(
        "show", show, audience="both", help="one plan in full — steps, deps, changelog",
        args=[reg.arg("id", help="a plan id, e.g. p-1")])
    reg.command(
        "changelog", changelog, audience="both", help="what has been done to one plan",
        args=[reg.arg("id", help="a plan id, e.g. p-1")])
    reg.command(
        "assign", assign, audience="both",
        help="give a step an owner; reassigning overwrites it and tells nobody",
        args=[reg.arg("step", help="a step id, e.g. s-1"),
              reg.arg("agent", help="the agent that owns it from now on"),
              reg.arg("--reason", help="why, for the changelog")])
    reg.command(
        "tick", tick, audience="both",
        help="mark a step done — nothing infers progress and nothing else writes it",
        args=[reg.arg("step", help="a step id, e.g. s-1"),
              reg.arg("--reason", help="why, for the changelog")])
    reg.command(
        "skip", skip, audience="both",
        help="mark a step skipped, with the reason; a skip is a state, never an absence",
        args=[reg.arg("step", help="a step id, e.g. s-1"),
              reg.arg("--reason", help="why it is being skipped — required")])
    reg.command(
        "note", note, audience="both", help="append a note to a step, or to a plan",
        args=[reg.arg("target", help="a step id (s-1) or a plan id (p-1)"),
              reg.arg("--text", help="the note")])
    reg.command(
        "checkpoint", checkpoint, audience="both",
        help="point a step at a brief or artifact — a path, URL or id, never its content",
        args=[reg.arg("step", help="a step id, e.g. s-1"),
              reg.arg("--ref", help="where the thing is: a path, a URL, an id"),
              reg.arg("--reason", help="why, for the changelog")])
    reg.command(
        "rework", rework, audience="both",
        help="re-enter a step: its try count goes up and its progress goes back to open",
        args=[reg.arg("step", help="a step id, e.g. s-1"),
              reg.arg("--reason", help="why it is being redone")])
    reg.command(
        "add-step", add_step, audience="both",
        help="invent a step on the fly, in a plan that is already running",
        args=[reg.arg("plan", help="a plan id, e.g. p-1"),
              reg.arg("name", repeat=True, help="what the step is"),
              reg.arg("--reason", help="why, for the changelog")])
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
              reg.arg("--reason", help="why, for the changelog")])
    reg.command(
        "dep", dep, audience="both",
        help="record that a step comes after others — data the lead reads, not control flow",
        args=[reg.arg("step", help="a step id, e.g. s-2"),
              reg.arg("--after", repeat=True,
                      help="a step it comes after; repeat for a join"),
              reg.arg("--reason", help="why, for the changelog")])


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
# It states the condition, the owner and the route, and stops. What a step IS, and what
# each verb does to one, is `sb plugin plans` and the design doc — repeating it here would
# be a second copy going stale against the verbs in this same file.
GUIDE = """\
Plan-making — read this when a job comes up, not before.

WHEN A PLAN EXISTS

  A plan exists exactly when the work is heading for a change that will land. Small is not
  exempt: a one-line docs change bound for a PR gets a plan, only a short one.

  Everything else runs without one — investigation, questions, scouting, review-only work,
  anything a single agent answers and reports, and everything a dispatcher does.

  Investigation produces a plan rather than living inside one. Make it once the outcome is
  known and there is a clear path from what was found through to a merged PR. Investigation
  is a step only when it is one piece of an already-shaped job.

WHO MAKES IT

  The worktree's owner: the lead of that worktree, or the sole worker where there is no
  lead. A sole worker counts as a lead for this and nothing else — making the plan for the
  work you were given is not going beyond your task, it is how the task is carried.

  A dispatcher is never involved in a plan. It relays work and makes agents and worktrees;
  it does not plan, own, tick or read one.

HOW TO MAKE IT

  Look for a template first — you are not expected to know one exists:

      sb plugin plans template list          browse them
      sb plugin plans template use <name>    start a plan from one

  Take a template if it fits and start from `create` if none does:

      sb plugin plans create "<what this plan is for>" --step "…" --step "…"

  A plan may be created with some of its steps already done — but not a step whose exit
  condition is a gate. Skip that one with the reason, which is visible, rather than
  starting it complete, which is not.

  Then keep it honest. Nothing infers progress: `tick` when a step is done, `skip` with the
  reason when it will not be, `rework` when it comes back, and re-plan on what you now know
  rather than executing a split you decided before you knew anything.

  `sb plugin plans` lists every verb; `sb plugin plans show <id>` renders one plan in full.
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
    """
    title = " ".join(str(w) for w in (args.title or ())).strip()
    steps = [str(s).strip() for s in (args.step or ()) if str(s).strip()]
    notes = [str(n).strip() for n in (args.note or ()) if str(n).strip()]
    # The reason is in here with the rest: it is the field every later verb carries into
    # the changelog, and the cap is about a record staying readable when it is shown.
    bad = _cap(title, *steps, *notes, args.reason)
    if bad:
        return bad

    doc, seal = _read(ctx.state_dir)
    who = ctx.agent or "human"
    where, how = _workspace(ctx)
    plan = {"id": f"p-{doc['next_plan']}", "workspace": where, "workspace_from": how,
            "checkout": str(_here(ctx)), "title": title,
            "steps": [], "changelog": [], "notes": [_note(n, who) for n in notes],
            "created_by": who, "created_at": int(time.time())}
    doc["next_plan"] += 1
    for name in steps:
        plan["steps"].append(_step(f"s-{doc['next_step']}", name))
        doc["next_step"] += 1

    made = ", ".join(s["id"] for s in plan["steps"])
    detail = f"{_count(plan['steps'])} ({made})" if made else "empty"
    if how == UNAVAILABLE:
        # In the append-only record as well as in the field, because this is the one thing
        # about a plan that was never true of the job and cannot be re-derived later: sb
        # was not reachable at the moment this plan was made.
        detail += "; workspace unresolved — sb did not answer"
    _log(plan, who, "create", args.reason, detail)
    doc["plans"].append(plan)
    _write(ctx.state_dir, doc, seal)
    # `{}` and not the library: every step `create` makes owns its own words, so there is
    # no link to resolve and no reason to open a file that could refuse after this write.
    shown = _shown(plan, {})
    return Result(human=_full(shown), data=shown)


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
    plans = _read(ctx.state_dir)[0]["plans"]
    here = _here(ctx)
    if not args.all:
        plans = [p for p in plans if _same(p.get("checkout"), here)]
    if not plans:
        return Result(human="(no plans on this worktree)" if not args.all
                            else "(no plans in this repo)", data=[])
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
    return Result(human="\n".join(_line(p, workspace=args.all) for p in views), data=views)


def show(ctx, args) -> Result:
    """One plan in full, with everything that is read rather than held read now.

    Two resolutions happen here and neither is written back. A named step becomes the words
    in the library, which is why an edit to a definition reaches a plan made last week; and
    every owner's status and the plan's own condition are read off sb at this instant,
    which is why a dead owner is on the line the moment a lead looks at it.
    """
    doc, _ = _read(ctx.state_dir)
    plan = _find(doc, args.id)
    if plan is None:
        return _missing(doc, args.id)
    # Resolved HERE and never in the file: this is the moment a link becomes text, which is
    # why an edit to a definition reaches a plan that was made last week and is running now.
    lib, bad = _lib([plan])
    if bad:
        return bad
    shown = _viewed(_shown(plan, lib), _Live(ctx))
    return Result(human=_full(shown), data=shown)


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


# -- the step lifecycle --------------------------------------------------------
#
# Eight verbs, and every one of them is `_on_step` (or, for the two that address a plan,
# the same three moves written out): read, change the ONE step named, log, write. Nothing
# here rewrites a plan wholesale — a re-plan and a tick can land in either order and the
# loser is still in the file — and the single `_log` call per verb is why the changelog is
# the record of how the job ran rather than of what the file ended up looking like.


def assign(ctx, args) -> Result:
    """Give a step an owner. Reassigning is the same act as assigning the first time.

    The design says so plainly: when an owner dies the lead dispatches a replacement and
    assigns the step to it, which is not a special case and gets no special handling. What
    it also says is that this tells the old owner NOTHING — there is no core verb that can
    tell a running agent anything, and inventing a notification here would be a second
    thing that believes it knows who is working. So the old name goes into the changelog
    and nowhere else, and closing the agent it came from is the lead's job.
    """
    agent = str(args.agent or "").strip()
    if not agent:
        return _needs("agent", "a step's owner is an agent name")
    bad = _cap(agent, args.reason)
    if bad:
        return bad

    def change(step: dict, who: str) -> str:
        was = step.get("owner")
        step["owner"] = agent
        return f"{step['id']} → {agent}" + (f", was {was}" if was and was != agent else "")

    return _on_step(ctx, args.step, "assign", args.reason, change)


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
                    lambda step, who: _progress(step, DONE, args.reason))


def skip(ctx, args) -> Result:
    """Skipped, with the reason — the half of progress that is not a tick.

    The reason is required, and that is the exchange the design makes: a step may be
    skipped rather than done, so a gate can be got past without a human, and what is paid
    for that is a state on the board with a sentence beside it. Skipping without one would
    be an omission wearing a state's clothes, and an omitted step is invisible — which is
    exactly what the design is buying its way out of.
    """
    reason = (args.reason or "").strip()
    if not reason:
        return _needs("--reason", "a skip is a state with a reason, never an absence — a "
                                  "bad call has to be visible to be questioned")
    bad = _cap(reason)
    if bad:
        return bad
    return _on_step(ctx, args.step, "skip", reason,
                    lambda step, who: _progress(step, SKIPPED, reason))


def note(ctx, args) -> Result:
    """A free-text note, on a step or on the plan itself. The target says which.

    Both exist because the design names both moments: the lead as it creates the plan, and
    whoever finishes a step as it is ticked. A plan-level note is the one that has nowhere
    else to go — what the job turned out to be about, what was learned — and the analysis
    pass reads a record cold, so notes are most of what makes one worth reading at all.

    `p-1` is the plan; `s-1` and a bare `1` are the step. A bare number means a step here
    for the same reason it does everywhere else in this file: every other verb addresses a
    step by its number alone, and the one place that would read it as a plan is the place
    it would be a surprise.
    """
    text = (args.text or "").strip()
    if not text:
        return _needs("--text", "a note is the text somebody reads back later")
    bad = _cap(text)
    if bad:
        return bad
    if not str(args.target or "").strip().lower().startswith("p"):
        return _on_step(ctx, args.target, "note", None,
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
    _log(plan, who, "note", None, f"on {plan['id']}: {_clip(text)}")
    _write(ctx.state_dir, doc, seal)
    shown = _shown(plan, lib)
    return Result(human=_full(shown), data=shown)


def checkpoint(ctx, args) -> Result:
    """Point a step at a brief or an artifact. A reference, and never the thing itself.

    The design says references, never content, and this is where that is kept honest: a
    ref carrying a newline is a paste and is refused. The cost of the other way is not
    disk — it is that a plan holding a copy of a brief is a second copy that goes stale,
    and a record read cold months later cannot tell which of the two was the real one.
    """
    ref = (args.ref or "").strip()
    if not ref:
        return _needs("--ref", "a checkpoint points at something: a path, a URL, an id")
    if "\n" in ref or "\r" in ref:
        why = ("a checkpoint is a reference, never content — that is more than one line. "
               "Write it to a file and point at the file.")
        return Result(ok=False, human=why, data={"error": why, "ref": _clip(ref)})
    bad = _cap(ref, args.reason)
    if bad:
        return bad

    def change(step: dict, who: str) -> str:
        step.setdefault("checkpoints", []).append(
            {"ref": ref, "by": who, "at": int(time.time())})
        return f"{step['id']} → {ref}"

    return _on_step(ctx, args.step, "checkpoint", args.reason, change)


def rework(ctx, args) -> Result:
    """Re-enter a step. Its try count goes up and its progress goes back to open.

    Rework is a number on a step, not an edge in the graph: a failed review sends its step
    back, and modelling that as a loop would make the plan cyclic to say something a
    counter says better. There is no ceiling on it — a loop that will not converge ends
    the way everything else does, with the lead blocking.

    A step that was never done can be reworked too, and that is not policed. `progress` is
    an open vocabulary, so this file cannot tell a step that is `done` from one a lead has
    parked in `waiting on Andrew`, and a verb that refused what it could not identify
    would refuse the interesting half. What it moved the step FROM is in the changelog, so
    a rework of an already-open step reads as exactly that.

    What this deliberately does NOT do is un-tick anything downstream. The design makes
    that the lead's judgement and says why: a rule that reopened everything reachable
    throws away good review, and one that reopened nothing merges work nothing reviewed.
    """
    bad = _cap(args.reason)
    if bad:
        return bad

    def change(step: dict, who: str) -> str:
        was = step.get("progress")
        step["tries"] = _counter(step.get("tries")) + 1
        step["progress"] = OPEN
        step["why"] = (args.reason or "").strip() or None
        return f"{step['id']} {was} → {OPEN}, try {step['tries']}"

    return _on_step(ctx, args.step, "rework", args.reason, change)


def add_step(ctx, args) -> Result:
    """A step invented while the job runs, in a plan that already exists.

    Its id comes from the same counter every other step comes from, so it is unique across
    the file and a spawn prompt citing it stays true. The reason matters more here than
    anywhere else: the design points out that rework leaves either a try count or a new
    step that looks like a recurring pattern, and the analysis pass can only tell those
    apart if the lead that added the step said which it was doing.
    """
    name = " ".join(str(w) for w in (args.name or ())).strip()
    if not name:
        return _needs("name", "a step is named so somebody can be told to do it")
    bad = _cap(name, args.reason)
    if bad:
        return bad

    doc, seal = _read(ctx.state_dir)
    plan = _find(doc, args.plan)
    if plan is None:
        return _missing(doc, args.plan)
    lib, bad = _lib([plan])             # before the write, so it cannot refuse after one
    if bad:
        return bad
    step = _step(f"s-{doc['next_step']}", name)
    doc["next_step"] += 1
    plan.setdefault("steps", []).append(step)
    who = ctx.agent or "human"
    _log(plan, who, "add-step", args.reason, f"{step['id']} {name}")
    _write(ctx.state_dir, doc, seal)
    return _changed(plan, step, lib)


def dep(ctx, args) -> Result:
    """Record that a step comes after others. Fan-out and join, stored as data.

    Nothing here executes, evaluates, orders or waits on an edge. A join waits because the
    lead does not start it, which is what "interpreted rather than executed" means, and
    there is no scheduler in this file to disappoint. Cycles are not refused either: the
    design says the graph stays acyclic, and it stays that way because rework is a counter
    rather than a back-edge — nothing traverses these, so a cycle is a lead's mistake to
    read, not a hang.

    What is refused is an edge that names nothing: a step that does not exist, a step in
    another plan, or the step itself. Those are typos, and an edge pointing at nothing
    renders as a dependency the lead will wait for forever.
    """
    after = [str(a).strip() for a in (args.after or ()) if str(a).strip()]
    if not after:
        return _needs("--after", "an edge says what a step comes after")
    bad = _cap(args.reason)
    if bad:
        return bad

    doc, seal = _read(ctx.state_dir)
    plan, step = _locate(doc, args.step)
    if step is None:
        return _no_step(doc, args.step)
    lib, bad = _lib([plan])             # before the write, so it cannot refuse after one
    if bad:
        return bad
    added = []
    for given in after:
        _, other = _locate(doc, given)
        if other is None:
            return _no_step(doc, given)
        if other is step:
            why = f"{step['id']} cannot come after itself"
            return Result(ok=False, human=why, data={"error": why, "id": given})
        if other not in (plan.get("steps") or ()):
            why = (f"{other['id']} is not in {plan['id']} — an edge joins steps of one "
                   f"plan, and nothing reads across plans")
            return Result(ok=False, human=why, data={"error": why, "id": given})
        # Compared as numbers, like every other id comparison in this file: `s-1` and a
        # bare `1` are one edge, and no comparison here can be a substring test — `in` on a
        # list of ids would already be right, but `in` on the string a hand-edit left there
        # would quietly report `s-1` as present in `s-10`. `_check` refuses that file, and
        # this is the second lock on the same door.
        n = _num(_STEP_ID, other["id"])
        if not any(_num(_STEP_ID, d) == n for d in step.setdefault("deps", [])):
            step["deps"].append(other["id"])
            added.append(other["id"])
    who = ctx.agent or "human"
    _log(plan, who, "dep", args.reason,
         f"{step['id']} after {', '.join(added)}" if added
         else f"{step['id']} already came after {', '.join(after)}")
    _write(ctx.state_dir, doc, seal)
    return _changed(plan, step, lib)


# -- the catalogue -------------------------------------------------------------
#
# Three verbs over two directories of JSON shipped beside this file. Read-only, all of them:
# `library` and `template list` render what is there, `name-step` and `template use` put
# LINKS and COPIES into the state file respectively, and nothing writes a definition.


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

    doc, seal = _read(ctx.state_dir)
    plan = _find(doc, args.plan)
    if plan is None:
        return _missing(doc, args.plan)
    try:
        added = _mint(doc, lib, wanted)
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
    bad = _cap(title, args.reason)
    if bad:
        return bad

    lib, bad = _lib()
    if bad:
        return bad
    doc, seal = _read(ctx.state_dir)
    who = ctx.agent or "human"
    where, how = _workspace(ctx)
    plan = {"id": f"p-{doc['next_plan']}", "workspace": where, "workspace_from": how,
            "checkout": str(_here(ctx)), "title": title,
            "steps": [], "changelog": [],
            "notes": [_note(str(n).strip(), who) for n in (spec.get("notes") or ())
                      if str(n).strip()],
            "created_by": who, "created_at": int(time.time())}
    doc["next_plan"] += 1
    try:
        for entry in (spec.get("steps") or ()):
            plan["steps"].extend(_from_template(doc, lib, entry))
    except _BadDef as e:
        return e.refusal()

    detail = f"from {wanted}: {_minted(plan['steps'], lib) or 'empty'}"
    if how == UNAVAILABLE:
        detail += "; workspace unresolved — sb did not answer"
    _log(plan, who, "template", args.reason, detail)
    doc["plans"].append(plan)
    _write(ctx.state_dir, doc, seal)
    shown = _shown(plan, lib)
    return Result(human=_full(shown), data=shown)


def _from_template(doc: dict, lib: dict, entry: Any) -> list[dict]:
    """One template entry, as the steps it puts in the copy. A name, or a link.

    An entry that says `def` is a link and goes through the same expansion `name-step`
    does — obligations included, since a template naming a merge and forgetting its review
    is exactly the memory this obligation exists to replace.
    """
    if not isinstance(entry, dict):
        raise _BadDef(f"a template's steps are objects, not {type(entry).__name__}")
    key = str(entry.get("def") or "").strip()
    if key:
        if key not in lib:
            raise _BadDef(f"a template names '{key}', which is not in the step "
                          f"library")
        return _mint(doc, lib, key)
    name = str(entry.get("name") or "").strip()
    if not name:
        raise _BadDef("a template holds a step with neither a name nor a def")
    step = _step(f"s-{doc['next_step']}", name)
    doc["next_step"] += 1
    return [step]


def _on_step(ctx, given: str, action: str, reason: Optional[str], change) -> Result:
    """Read, change the one step named, log, write. Every step verb is this.

    `change` mutates the step and returns the changelog detail — or a `Result`, for the
    refusal it could not make before the file was read. Having one shape for all of them is
    what makes "every mutating verb appends a changelog entry" a property of the file
    rather than a thing eight verbs each remember: a verb that skipped `_log` would have to
    not be written this way at all.
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
    return _changed(plan, step, lib)


def _progress(step: dict, to: str, why: Optional[str]) -> str:
    """Move a step's progress, and say what it moved from. `tick` and `skip` share this.

    One field, so complete and skipped cannot both be true — the second verb replaces the
    first rather than joining it, and the changelog is what says a correction happened.
    `why` is overwritten too, including with nothing: a step ticked after a skip must not
    keep the sentence explaining why it was skipped.
    """
    was = step.get("progress")
    step["progress"] = to
    step["why"] = (why or "").strip() or None
    return f"{step['id']} {was} → {to}"


def _add_note(step: dict, text: str, who: str) -> str:
    step.setdefault("notes", []).append(_note(text, who))
    return f"{step['id']}: {_clip(text)}"


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


def _no_step(doc: dict, given: str) -> Result:
    """No such step. The same shape as `_missing`, one id kind along.

    Steps are numbered from one counter across the whole file, so "the highest is s-7" is a
    true and useful thing to say from anywhere — and ids are never reused, so a step that is
    not here has never been here.
    """
    said = _flat(given)                 # see `_missing`: an id is never vetted text
    if _num(_STEP_ID, given) is None:
        why = f"'{said}' is not a step id — they look like s-1"
    else:
        high = _high(_STEP_ID, (s.get("id") for p in doc["plans"]
                                for s in (p.get("steps") or ())))
        why = (f"no step {said} — none has been made yet" if not high
               else f"no step {said} — the highest is s-{high}")
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
    `plans.json` somebody edited by hand, and a `name` out of a definition in the library.
    Escaped rather than stripped, so what is there is still visible — a forged row shows up
    as the `\\n` it actually is, on the one line it was always entitled to.
    """
    return _CONTROL.sub(_escape, str(text))


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


def _step(sid: str, name: Optional[str], *, key: Optional[str] = None,
          obliged_by: Optional[str] = None) -> dict:
    """One step, with every field the design names it carries and nothing more.

    `tries` starts at 1 rather than 0: a step being worked is on its first try, and a count
    above one is what renders. `deps` are the ids this step comes after — fan-out and join
    are edges the lead reads, never control flow anything executes. `why` is the reason for
    whatever `progress` currently says, and is here as an explicit null rather than a key
    that appears the first time something is skipped: the shape of a step is documented, and
    a field that exists only sometimes is a field every reader has to guess about.

    `name` and `def` are the two ways a step says what it is, and exactly one of them is
    filled. An on-the-fly step owns its words; a named one owns a LINK, and its `name` stays
    null so that there is no copy of the definition here to go stale — the text is resolved
    at render time and an edit to the library reaches this step wherever it is. `obliged_by`
    is the id of the step that brought this one, which is how a review says which merge it
    belongs to and how PR7's gate will find it. Both are explicit nulls for the same reason
    `why` is.
    """
    return {"id": sid, "name": name, "def": key, "obliged_by": obliged_by,
            "progress": OPEN, "why": None, "owner": None,
            "tries": 1, "notes": [], "deps": [], "checkpoints": []}


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

    `"obliges": "merge-review"` iterates one letter at a time, and what came out of that was
    a refusal saying `'merge' obliges 'm', which is not in the step library` — technically a
    refusal, and useless to whoever has to fix the file.
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

    A file that IS there and is not readable is refused, with its path, exactly as
    `plans.json` is. Silently skipping it would leave a plan resolving a link to nothing
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


def _mint(doc: dict, lib: dict, key: str) -> list[dict]:
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
        steps.append(_step(f"s-{doc['next_step']}", None, key=k,
                           obliged_by=steps[by]["id"] if by is not None else None))
        doc["next_step"] += 1
    return steps


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
    return dict(step, name=str(spec.get("name") or "").strip() or key)


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


def _read(d: Path) -> tuple[dict, dict]:
    """The whole file and its seal — the changelogs as they were, for `_write` to check.

    Never raises for a file that is not there yet. The two counters are recomputed as
    floors over every id present, so a hand-edited file that lost one still cannot mint an
    id that has already been written down somewhere else.

    A file that is there and unreadable is a REFUSAL, naming the path, rather than a fresh
    empty document: starting over would silently replace every plan in the repo on the next
    `create`, and the records are the whole point of keeping them. The failing verb stops,
    nothing is written, and a human fixes or moves the file.

    Unreadable is checked all the way down, not just at the top level, and the reason is
    the seal rather than tidiness: it is keyed on the plan id, so two plans sharing an id —
    or two with no id at all — collapse into one entry and `_write`'s drop check passes
    over the plan whose changelog is no longer in it. Every shape that would break that
    assumption is refused here, where nothing has been written yet, which is cheaper than
    a `_write` that has to be right about a file it was already lied to about.
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
        if _counter(doc.get("format", FORMAT)) > FORMAT:
            # The one thing a version marker can do, and the only moment it can do it: a
            # file from a newer plans plugin is refused rather than written back in this
            # one's shape. Stamped and never checked, it would be a field that only ever
            # documented the damage afterwards.
            raise _refuse(f, f"was written by a newer plans plugin (format "
                             f"{doc.get('format')}; this one speaks {FORMAT})")
        _check(f, doc.get("plans") or [])
    else:
        doc = {"format": FORMAT, "next_plan": 1, "next_step": 1, "plans": []}
    doc.setdefault("format", FORMAT)
    doc.setdefault("plans", [])
    plans = doc["plans"]
    doc["next_plan"] = max(_counter(doc.get("next_plan")),
                           _high(_PLAN_ID, (p.get("id") for p in plans)) + 1)
    doc["next_step"] = max(_counter(doc.get("next_step")),
                           _high(_STEP_ID, (s.get("id") for p in plans
                                            for s in (p.get("steps") or ()))) + 1)
    return doc, _seal(doc)


def _refuse(f: Path, what: str) -> ValueError:
    """The one refusal, so every malformed file says the same two things.

    Returned rather than raised, so the caller reads as `raise _refuse(...)` and nothing
    can call this and carry on. What it says is the path and that the file is safe: a
    message that only says "no" sends a human looking for a bug in sb.
    """
    return ValueError(f"{f} {what}. Nothing here will overwrite it — fix it or move it "
                      f"aside.")


def _check(f: Path, plans: list) -> None:
    """Every shape inside `plans` that the rest of this module assumes, checked once.

    Plan ids are checked for BEING there and for being distinct, because both are load
    bearing: the seal is keyed on the id, and `_write` decides a plan was dropped by
    looking its id up. Compared as numbers, so `p-1` and a bare `1` are the one plan they
    name rather than two rows that pass a string comparison.

    Every container a verb APPENDS to is checked for being a list, for the same reason the
    ids are: not tidiness, but that the code after this point assumes it. A `notes` that is
    null gives a raw `AttributeError` naming no file instead of the refusal this function
    exists to give, and a `deps` that is a string is worse than a crash — `in` degrades to a
    substring test, so `s-1` reads as already present in `"s-10"` and the edge is silently
    dropped. Refusing here is refusing before anything is written.
    """
    seen: set[int] = set()
    steps_seen: set[int] = set()
    for plan in plans:
        if not isinstance(plan, dict):
            raise _refuse(f, f"holds a {type(plan).__name__} where a plan should be")
        n = _num(_PLAN_ID, plan.get("id"))
        if n is None:
            raise _refuse(f, f"holds a plan with no usable id ({plan.get('id')!r})")
        if n in seen:
            raise _refuse(f, f"holds two plans called p-{n}, and ids are never reused")
        seen.add(n)
        steps = plan.get("steps", [])
        if not isinstance(steps, list) or any(not isinstance(s, dict) for s in steps):
            raise _refuse(f, f"has a p-{n} whose steps are not a list of steps")
        for step in steps:
            # Checked across the whole file, not per plan, because there is one step
            # counter for the whole file — and because everything after PR1 addresses a
            # step by its number alone. A twin `s-1` would take a tick meant for the other
            # one and neither would say so; a step with no id cannot be ticked at all.
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


def _seal(doc: dict) -> dict:
    """Every plan's changelog as it stands, keyed by plan NUMBER. Compared on the way out.

    The number rather than the string, so that `p-1` and a bare `1` cannot seal one plan
    and be looked up as another. `_read` has already refused a file where two plans share
    one, which is what makes a dict safe to key on it at all.
    """
    return {_num(_PLAN_ID, p.get("id")): json.dumps(p.get("changelog") or [], sort_keys=True)
            for p in doc["plans"]}


def _write(d: Path, doc: dict, seal: dict) -> None:
    """Whole-file rewrite via tmp + `os.replace`, under the lock sb is already holding.

    `os.replace` is atomic within a directory, so a reader sees the old file or the new one
    and never half of one — which matters even though sb serialises the writers, because
    `plans.json` is a plain file somebody may well `cat` while a job is running.

    The append-only check is here, at the single write, rather than trusted to each verb.
    A command changes the steps it names; if one ever rewrites a plan wholesale it will
    take the changelog with it, and that failure is silent everywhere except here.

    Both halves of "append-only" are checked, because dropping the plan is the easier way
    to lose a changelog than editing one: a plan that was read and is not being written
    back has lost every entry it had, and the design says records are kept and never
    erased — cleanup means dropping out of the UI.

    What `os.replace` buys is readers, not crashes: a power loss between the rename and
    the blocks reaching disk can still cost the last write, and there is no `fsync` here.
    That is `todo`'s trade taken deliberately, and the cost is one command's worth of
    changelog, not the file.
    """
    here = {_num(_PLAN_ID, plan.get("id")) for plan in doc["plans"]}
    gone = [n for n in seal if n not in here]
    if gone:
        raise ValueError(f"this write would have dropped "
                         f"{', '.join(f'p-{n}' for n in sorted(gone))} and its changelog; "
                         f"plans are kept, never erased")
    for plan in doc["plans"]:
        n = _num(_PLAN_ID, plan.get("id"))
        was = seal.get(n)
        if was is None:
            continue                    # a plan created by this command; nothing to keep
        old = json.loads(was)
        now = plan.get("changelog") or []
        if not isinstance(now, list) or now[:len(old)] != old:
            raise ValueError(f"p-{n}'s changelog is append-only, and this write would have "
                             f"dropped or rewritten {len(old)} entries")
    tmp = d / f".{FILE}.tmp"
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, d / FILE)


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
    words, so annotating a step in place would write an owner's status into `plans.json` on
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
    """The step this id names, and the plan holding it. Searched across every plan.

    A step is addressed by its number ALONE, with no plan named beside it, which is what
    makes `sb plugin plans tick s-7` something an agent can be told at spawn and type
    without first looking anything up. `_read` has already refused a file where two steps
    share a number, so the first match is the only match.
    """
    n = _num(_STEP_ID, given)
    if n:
        for plan in doc["plans"]:
            for step in plan.get("steps") or ():
                if _num(_STEP_ID, step.get("id")) == n:
                    return plan, step
    return None, None


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
    where = f"{_where(p):<24}" if workspace else ""
    # The condition is a column on the listing and not a footnote: what a lead scanning
    # `list` wants first is which of these plans anybody is still on.
    cond = f"{str(p.get('condition') or ''):<11}" if p.get("condition") else ""
    return (f"{p['id']:<6}{_count(p.get('steps') or []):<10}{cond}{where}"
            f"{_flat(p.get('title') or '(untitled)')}")


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
    lines = [f"{p['id']}  {_flat(p.get('title') or '(untitled)')}",
             f"  workspace   {_where(p)}",
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


def _step_lines(steps: list) -> list[str]:
    """One line per step, plus a line each for what hangs off it.

    The reason, the refs and the notes are written out rather than counted. A step line
    saying `[2 checkpoints]` tells a lead there is something to go and look for and not
    where it is, and a skipped step whose reason is twenty lines down in the changelog is
    the absence this design exists to avoid — `show` is the place a plan is read in full.
    """
    out = []
    for s in steps:
        bits = [f"{_flat(s.get('id', '?')):<6}{_flat(s.get('progress', '?')):<10}"
                f"{_flat(s.get('name') or '')}"]
        if _defkey(s):
            # The link is shown, not just what it resolves to: a lead deciding whether to
            # edit a definition or write a variant has to be able to see which steps are
            # links, and a resolved name looks exactly like a step somebody typed.
            bits.append(f"[{_flat(_defkey(s))}]")
        if s.get("obliged_by"):
            bits.append(f"obliged by {_flat(s['obliged_by'])}")
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
        if _counter(s.get("tries")) > 1:
            bits.append(f"try {_flat(s['tries'])}")
        out.append("  ".join(bits))
        if s.get("why"):
            out.append(f"    — {_flat(s['why'])}")
        out.extend(f"    ref   {_flat(c.get('ref'))}" for c in (s.get("checkpoints") or ()))
        out.extend(f"    note  {_flat(n.get('text'))}  ({_flat(n.get('by'))}, "
                   f"{_when(n.get('at'))})"
                   for n in (s.get("notes") or ()))
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


def _changed(plan: dict, step: dict, lib: dict) -> Result:
    """What a step verb hands back: the plan it was in, and the step as it now stands.

    The step alone, not the whole plan — a tick that printed the entire plan back would
    bury the one line that changed, and `show` is a command away. `data` names the plan
    anyway, because a machine reader given only a step has lost which plan it belongs to
    and there is no verb that maps one back to the other. Resolved, like every other read:
    a tick on a named step should say what it ticked and not print a null.
    """
    shown = _resolve(step, lib)
    lines = [f"{plan['id']}  {_flat(plan.get('title') or '(untitled)')}"]
    lines.extend(f"  {ln}" for ln in _step_lines([shown]))
    return Result(human="\n".join(lines), data={"plan": plan["id"], "step": shown})


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
    return Result(human="\n".join(lines), data={"plan": plan["id"], "steps": shown})


def _def_lines(key: str, spec: dict, lib: dict, *, full: bool) -> str:
    """One definition as the library renders it: its name, and what naming it does."""
    lines = [f"{_flat(key):<16}"
             f"{_flat(str(spec.get('name') or '').strip() or '(unnamed)')}"]
    parts = _names(key, spec, "steps")
    if parts:
        lines.append(f"    composes    {', '.join(_flat(x) for x in parts)}")
    for ob in _obliges(lib, key):
        lines.append(f"    obliges     {_flat(ob)} — added with it, skippable with a reason, "
                     f"never omitted")
    if full:
        lines.extend(_about(spec))
    return "\n".join(lines)


def _template_lines(key: str, spec: dict) -> str:
    lines = [f"{_flat(key):<16}"
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
    high = _high(_PLAN_ID, (p.get("id") for p in doc["plans"]))
    return (f"no plan {said} — none has been made yet" if not high
            else f"no plan {said} — the highest is p-{high}")
