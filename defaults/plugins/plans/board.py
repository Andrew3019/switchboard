"""What this plugin draws under its worktree on the board. The board's hook, plugin side.

`switchboard/board.py` looks for this file and for `board_lines` on it, and imports
neither unless both are there — which is what makes a board with no plugin drawing on it
cost nothing at all. A plugin that never wants to appear simply ships no `board.py`.

TWO RULES SHAPE EVERYTHING BELOW, and they are the same rule twice.

**Nothing here asks anybody anything.** `list` and `show` build a `_Live` and spend a
`_Budget` of seconds on `sb status`; a board redraws every couple of seconds, per group,
and cannot. It does not have to: the board hands over the `AgentStatus` rows of the very
worktree being drawn, and those rows already carry `state`, `gone` and `display_state` —
reconciled once per snapshot by the collector, which is the one process that asks. So
`_Rows` below is `_Live` with its single question already answered off what was handed in,
and every derivation on top of it — an owner's status, a plan's condition — is the shared
one, unchanged and unduplicated. The only thing this file touches is the plan files and one
`os.stat` of a checkout, both of which `_Live` already treats as free.

**A board is a picture and a listing is a listing.** This file used to draw `_line` and
`_step_lines` — the same two functions `list` and `show` draw with — so that a change to
how a plan reads reached the board for free. That rule bought consistency and cost the
board the one thing it is for: a plan's SHAPE. A plan is a DAG, `after s-1, s-2` is that
DAG spelled out in words, and a human glancing at a board to see where a job has got to
should not have to reassemble a graph in their head from a column of trailing clauses.
So the board now draws its own view — a header per plan, and its steps as a flowchart —
and `show` remains the place a plan is read in full, line by line, with its whys, refs,
notes and gates. Two views of one record, deliberately, rather than one view twice.

What that view shows is the second editorial decision, and it is deliberately thin:

  * A HEADER per plan — id, display name, condition, step count, in that order. The plan's
    DISPLAY and not its title, for the reason the steps draw theirs: a heading is read at a
    glance and a title is a sentence. The id is the
    handle you type, the display name is what the job is, and the two after it are how it
    is going and how big it is. Nothing else: the workspace is the group this hangs under,
    and the checkout and the changelog are what `show` is for.

  * THE STEPS AS A FLOWCHART, their DISPLAY NAMES only — the short board label every step
    is required to carry, falling back to its full name where a hand-edit left none — laid
    out left to right in dependency order. Nothing is clipped per cell: a display name is
    short because its author made it short, and the pane's own clip from the right is the
    only one left. A step missing its label or its dep is drawn RED (see `RED`).
    Progress is COLOUR rather than a column, because a column of `open`/`done` down the
    side of a graph is the same word eight times and the graph is what carries the
    meaning. Nothing else on a step — no id, no owner, no try count, no `why`. Those are
    all in `show`, one command away, and every one of them on the board would turn a
    picture back into the listing this replaced.

  * EVERY step, not just the open ones. The old board hid ticked steps because a listing
    of open work is what a glance wanted. A graph with its finished nodes cut out is not
    a smaller graph, it is a wrong one — the edges lead nowhere and the shape of the job
    stops being legible. Colour is what makes showing them cheap: done is green and
    reads as behind you, and the eye goes to what is not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from switchboard.board import _visible_len

from . import (CLOSED, DONE, OPEN, SKIPPED, _STEP_ID, _defective, _flat, _is_record, _lib,
               _num, _read, _shown, _some, _tier, _viewed, _Live)


# A SECTION OF THE BOARD'S OWN, under the tree, rather than a block hanging off the last
# row of a worktree group. `switchboard/board.py`'s seam reads this name and draws the
# heading; deleting the line puts these lines back under their group and changes nothing
# else. See `BOARD_SECTION` there.
#
# Why a section: a block under a group reads as a footnote to those agents, which is what
# a line or two ABOUT them should read as. What this plugin draws is a picture of a job —
# a header and a flowchart, with a shape of its own and its own alignment — and a picture
# hung off the end of a tree at a hanging indent is a picture nobody can see the edges of.
SECTION = "PLANS"

# How much bare line a dependency arrow gets before its channel. The gap between two
# columns is this stub, then one channel per bundle of edges, then the arrowheads — so a
# plain one-to-one hop draws as `STUB` dashes plus `→`, and `1` is what makes that `──→`.
#
# Named rather than left as the literal it was in two places, because the two are the same
# number and nothing said so: `span` counts the stub to size the block and `ch` counts it
# again to place the first channel, and an arrow shortened in one and not the other draws
# a picture whose lines start where nothing ends. The number is the whole of the arrow
# length knob — 0 gives `─→`, 2 gives the `───→` this was.
STUB = 1

# What a step's progress is drawn as. SGR, because the seam now carries colour and
# nothing else: `switchboard/board.py` strips every control character a plugin hands over
# except the select-graphic-rendition sequences, so this is the one kind of escape that
# survives. `open` is deliberately UNPAINTED — it is the ordinary state and the majority
# of every plan, and a colour that says "normal" is a colour that says nothing.
#
# `progress` is an open vocabulary (see the module docstring in `__init__.py`): a lead may
# write `waiting on Andrew` into a step, and that is not an error. So anything this does
# not know is drawn in yellow — visible, and honestly "something other than the three".
GREEN, GREY, YELLOW, PLAIN = "\x1b[32m", "\x1b[90m", "\x1b[33m", "\x1b[0m"
DIM = "\x1b[2m"

# What an INCOMPLETE plan is drawn in — the third of the three doors the plugin puts in
# front of a plan missing a display name or a dep (`_defects` in `__init__.py`). The other
# two are a refusal at the shape verbs and a warning on every other write; this one is the
# only door that reaches a plan nobody has typed a verb at since it was hand-edited. Red
# beats the progress colour on the steps at fault and paints the header of the plan holding
# them, because a defect the eye has to hunt for on a board is a defect nobody fixes.
RED = "\x1b[31m"

# The most steps one plan's chart is drawn for. A backstop and not a layout rule: the grid
# below is O(rows × columns) and a plan nobody pruned should not be able to make a board
# redraw expensive. Past this the chart is simply DROPPED and nothing says it was: the
# header renders exactly as always, so a plan over the cap draws as a bare header with no
# picture under it. Said plainly here because it is the one thing about this constant a
# reader would otherwise have to discover from a screen that looks like a rendering bug.
MAX_STEPS = 40


def board_lines(state_dir: Path, workspace: str, rows: list) -> list:
    """This worktree's plans, as `(line, workspace)` pairs, or nothing at all.

    The pair is the seam's opt-in for an associated agent (`board._hook_lines_owned`): every
    line here is paired with the workspace it belongs to, which the board reads as a click
    target and a highlight key. A bare list of strings would still be accepted and own
    nobody; this plugin pairs so its rows point at their plan's main agent.

    Matched on the WORKSPACE NAME and not on the checkout path, which is the one place
    this differs from `list`: the board groups by the name the store holds, that name is
    what `create` filed the plan under, and the board has no checkout path to offer. A
    plan whose workspace is null — a plain clone, or one not yet repaired by `show`/`list`
    after sb was unavailable at creation — is in no group and so is drawn by nobody. Once
    a CLI read persists its workspace, the next render picks it up without asking anything.

    Every failure here is silence, enforced on the board's side as well as this one: a
    board is what a human looks at to find out that something has gone wrong, and a plugin
    is not allowed to be the reason it stopped drawing.
    """
    if not workspace:
        return []
    plans = [p for p in _read(Path(state_dir))[0]["plans"]
             if p.get("workspace") == workspace]
    if not plans:
        return []
    lib, bad = _lib(plans)
    if bad:
        # A catalogue with a bad definition in it is a real problem and `sb plugin plans
        # list` says so in full. Saying it here would put a refusal where a plan should be,
        # on a screen with no room to explain it and no way to act on it.
        return []
    live = _Rows(rows)
    out: list[str] = []
    for p in plans:
        v = _viewed(_shown(p, lib), live)
        # Read off the RESOLVED plan, because a named step's display lives in its
        # definition: asking the stored step would report every library step as defective.
        plan_bad, bad = _defective(v)
        out.append(_header(v, plan_bad or bool(bad)))
        steps = v.get("steps") or []
        # Item 2, best effort: where a single PR number is on the change record, the open-PR
        # and merge-PR steps carry it in their board label. A visual nicety only — it never
        # decides anything, so a record with no number just draws the labels it always did.
        pr = _pr_number(v)
        if pr is not None and steps:
            steps = [_pr_labelled(s, pr) for s in steps]
        if steps:
            # One space, not two: a chart's own cells are padded (`_cell`), so the first name
            # already sits a column in from wherever this block starts.
            out.extend(" " + line for line in _chart(steps, bad))
        else:
            # ROBUST EMPTY RENDER. A document with no chart — a legacy stepless record, or a
            # sparse shaped placeholder like the ones that read as a bare header before — still
            # says something useful: where it is (`phase`) and the first line of what it is
            # about. A header alone on the board is a row nobody can act on.
            line = _empty_line(v)
            if line:
                out.append(" " + line)
    # ITEMS 1 & 3, THE ASSOCIATION. Every line of every plan on this worktree is paired with
    # the WORKSPACE it was drawn for — the one string this hook is handed, and the one every
    # plan here was filtered to. That workspace is the plan's main agent's name (`sb delegate`
    # names an agent and its workspace after each other), so the board turns it into a click
    # that focuses that agent and a highlight that lights the plan of whichever agent is here
    # or under the cursor. A plugin that returns bare strings is unchanged; this one opts in
    # by pairing, and the board reads the pair (`board._hook_lines_owned`).
    return [(line, workspace) for line in out]


def _empty_line(p: dict) -> str:
    """A one-line stand-in for a chart when a document has no steps.

    Drawn dim, because it is a placeholder for the picture rather than the picture. It reads
    the coarse `phase` and the first line of whatever the change record or the notes say the
    job is — enough for a lead scanning the board to tell an empty row apart from the next
    empty row, which a bare header cannot do.
    """
    change = p.get("change") if isinstance(p.get("change"), dict) else {}
    bits: list[str] = []
    if _some(change.get("phase")):
        bits.append(_flat(change["phase"]))
    gist = next((change.get(k) for k in ("solution", "cause", "request", "contract")
                 if _some(change.get(k))), None)
    if not _some(gist):
        notes = p.get("notes") or []
        gist = (notes[0] or {}).get("text") if notes and isinstance(notes[0], dict) else None
    if _some(gist):
        bits.append(_flat(gist).split(". ")[0])
    if not bits:
        return ""
    return DIM + "  ·  ".join(bits) + PLAIN


# The two skeleton steps a single PR number is stamped onto — the open-PR step and the
# merge step, by their `anchor` (`create-pr` anchors `pr`, `merge` anchors `merge`). Read
# off the anchor and not the def name, so a hand-authored step anchored the same way is
# labelled the same way, and a rename of a library def never silently drops the number.
_PR_STEPS = ("pr", "merge")


def _pr_number(p: dict) -> Any:
    """The single PR number on a change record, or None. Best effort and single-PR only.

    `change.pr` is one `{number, head}` and never a list, so "single PR" is what the record
    can even hold — there is no multi-PR case to guard against here. Every lookup is guarded
    because this draws on a board and a malformed record may never be the reason a plan stops
    drawing; anything but a real number or a non-empty string reads as "no number", and the
    labels render exactly as they did before the number existed. A bool is refused explicitly
    — `True` is an `int` to Python and `#True` is not a PR.
    """
    change = p.get("change") if isinstance(p.get("change"), dict) else {}
    pr = change.get("pr") if isinstance(change.get("pr"), dict) else {}
    n = pr.get("number")
    if isinstance(n, bool):
        return None
    if isinstance(n, int):
        return n
    if isinstance(n, str) and n.strip():
        return n.strip()
    return None


def _pr_labelled(step: dict, pr: Any) -> dict:
    """A copy of `step` with the PR number appended to its display, if it is a PR step.

    A COPY, never the step in place: `_viewed` hands back dicts that other renderings share,
    and stamping the number onto one would leak `#123` into `show` and the store. Only a step
    anchored at the open-PR or merge band is touched; everything else is returned unchanged,
    so the annotation is confined to the two steps the number is actually about. The label is
    the step's own board name with ` #<n>` after it — the display, so `_label` draws it
    straight — and falls back to the bare tag only for the degenerate step with no name at
    all, which is already drawn `?` and is a defect the number does not make worse.
    """
    if str(step.get("anchor") or "").strip() not in _PR_STEPS:
        return step
    base = _flat(step.get("display") or step.get("name") or "")
    tag = f"#{pr}"
    return {**step, "display": f"{base} {tag}" if base else tag}


def _header(p: dict, bad: bool = False) -> str:
    """One plan's line: what to type, what it is, how it is going, how big it is.

    That order and not the listing's. `list` leads with the count and the condition
    because it is a table and a lead scans a column; this is a heading over a picture,
    and what a heading is for is saying which job the picture is of. So the name comes
    second, straight after the handle, and the two facts about its state trail it.

    THE PLAN'S `display`, AND NOT ITS TITLE. A title says what the job is in a sentence,
    which is what `show` is for; this line is a heading, and a heading that wraps or gets
    cut mid-clause has stopped being one. A plan's display is longer than a step's — it
    owns this whole line where a step owns a cell — and it is a display VERSION of the
    title rather than an abbreviation of it. A plan authored without one falls back to the
    title, which is every plan made before the field was required and is drawn `bad`.

    The condition is drawn as the bare word rather than `_condition`'s word-plus-sentence.
    The sentence exists because `show` is read by somebody deciding what to do about a
    plan; a board is read by somebody deciding whether to go and look at all.
    """
    steps = p.get("steps") or []
    n = len(steps)
    meta = [str(p.get("condition") or "")] if p.get("condition") else []
    # THE TIER TAG, first among the state facts: a record now draws a step chart like a
    # plan's, so `direct` / `shaped` is what tells the two apart at a glance. Then the step
    # count — a record carries its skeleton, so it counts steps like a plan; only a legacy
    # stepless record or a sparse shaped placeholder reads `empty`.
    meta.append(_tier(p))
    meta.append(f"{n} step{'' if n == 1 else 's'}" if n else "empty")
    name = _flat(p.get("display") or p.get("title") or "(untitled)")
    head = f"{_flat(p.get('id') or '?')}  {name}"
    return ((RED + head + PLAIN if bad else head)
            + DIM + "  ·  " + "  ·  ".join(meta) + PLAIN)


def _chart(steps: list, bad: set | None = None) -> list[str]:
    """A plan's steps as a left-to-right flowchart: names, arrows, and nothing else.

    THE WHOLE LAYOUT IN FOUR MOVES, and each one is a function below:

      1. `_layers` puts every step in a column — the longest path from any step it does
         not depend on. Longest and not shortest, so a step sits to the RIGHT of
         everything it waits for however many hops away that is, which is what makes the
         picture readable as "this before that".
      2. `_route` inserts a placeholder for every edge that skips a column, so that no
         edge has to be drawn across a cell that belongs to something else. This is what
         lets step 4 be a grid of adjacent hops rather than a general line router.
      3. `_place` gives every node a row, preferring the topmost row of the things it
         waits for, so a chain stays on one line and a fan-out spreads down from it.
      4. `_draw` fills a character grid — names in the column cells, box-drawing in the
         gaps between them — and joins it into lines.

    A step with no `deps` is a root and starts at the left. Deps naming a step that is not
    in this plan are dropped, and so is a step depending on itself: both are data errors,
    and neither may be a reason the board draws nothing. NOTHING REPORTS THEM — `show`
    prints `after s-99` verbatim and `_check` does not resolve a dep — so what the reader
    sees of either is a missing edge and no explanation. Dropping is still right (a board
    is not where a data error is diagnosed) but it is silent, and this docstring used to
    claim otherwise.
    """
    ids = [str(s.get("id")) for s in steps if s.get("id")]
    if not ids or len(ids) > MAX_STEPS:
        return []
    by_id = {str(s["id"]): s for s in steps if s.get("id")}
    deps = {i: _deps(by_id[i], i, by_id) for i in ids}

    layer = _layers(ids, deps)
    nodes, edges = _route(ids, deps, layer)
    row = _place(nodes, edges, layer)
    return _draw(nodes, edges, layer, row, by_id, bad or set())


def _deps(step: dict, i: str, by_id: dict) -> list[str]:
    """One step's deps as the ids of steps in this plan: resolved, de-duplicated, in order.

    RESOLVED AS NUMBERS, which is how every other id comparison in this plugin works —
    `dep` says so where it writes one (`__init__.py`): "`s-1` and a bare `1` are one edge".
    A lead edits a plan file in an editor, `_check` accepts a bare `1` in `deps`, and
    `show` renders it as `after 1`, so matching the STRINGS here drew no edge for exactly
    the dep a hand-edit is most likely to write — a board saying something different from
    `show` about one record. It also let a self-dep written as `1` past the `d != i` guard
    below and out into the next column as a spurious arrow.

    An id `_num` cannot read a number out of is matched literally instead, which is the
    old behaviour and the only one available: nothing can compare `abc` as a number.
    De-duplicated because `s-1` and `1` now resolve to one node, and two copies of one
    edge would be laid out and drawn twice.
    """
    num = {}
    for other in by_id:
        n = _num(_STEP_ID, other)
        if n is not None:
            num.setdefault(n, other)
    out: list[str] = []
    for raw in (step.get("deps") or ()):
        n = _num(_STEP_ID, raw)
        d = num.get(n) if n is not None else (str(raw) if str(raw) in by_id else None)
        if d is not None and d != i and d not in out:
            out.append(d)
    return out


def _layers(ids: list[str], deps: dict[str, list[str]]) -> dict[str, int]:
    """Which column each step sits in: one past the furthest thing it waits for.

    Cycle-safe by construction, because it has to be. `dep` records edges and refuses
    nothing, so `s-1 after s-2` and `s-2 after s-1` is a plan somebody can actually
    write; a recursion that trusted the graph to be acyclic would hang the render thread
    and take the board with it. A step already on the path being resolved contributes
    zero — the back edge is simply not counted — which draws a wrong picture of a plan
    that IS wrong, in finite time, rather than no board at all.
    """
    at: dict[str, int] = {}

    def of(i: str, path: frozenset) -> int:
        if i in at:
            return at[i]
        if i in path:
            return 0                            # a cycle; see the docstring
        here = path | {i}
        at[i] = max((of(d, here) + 1 for d in deps[i]), default=0)
        return at[i]

    for i in ids:
        of(i, frozenset())
    return at


def _route(ids: list[str], deps: dict, layer: dict) -> tuple[dict, list]:
    """Every edge made one column long, by inventing a node wherever one skips a column.

    `s-3 after s-1` where `s-2` also sits between them is an edge two columns long, and a
    grid that only ever draws a hop from one column to the next has nowhere to put it.
    The standard answer is the one taken here: give the edge a placeholder in each column
    it passes through, laid out and drawn exactly like a real node except that its cell is
    the line itself rather than a name. The picture then has no special case in it at all.

    Returns `{layer: [node, ...]}` and the adjacent-column edges as `(from, to)` pairs.
    Placeholder names are `("", n)` tuples, which cannot collide with a step id.
    """
    nodes: dict[int, list] = {}
    for i in ids:
        nodes.setdefault(layer[i], []).append(i)
    edges: list[tuple[Any, Any]] = []
    n = 0
    for i in ids:
        for d in deps[i]:
            at = layer[d]
            prev: Any = d
            while at + 1 < layer[i]:
                at += 1
                n += 1
                ghost = ("", n)
                nodes.setdefault(at, []).append(ghost)
                edges.append((prev, ghost))
                prev = ghost
            edges.append((prev, i))
    return nodes, edges


def _place(nodes: dict, edges: list, layer: dict) -> dict:
    """A row for every node: as near the top of what it waits for as is free.

    Column by column, left to right, so that everything a node waits for already has a
    row by the time the node is given one. Wanting the TOPMOST parent row and taking the
    next free row below it is what keeps a chain on one line — the ordinary case, and the
    one the picture must not get wrong — while a fan-out steps down from its source.

    Free means free IN ITS OWN COLUMN. Two nodes in different columns may share a row and
    usually do; two in the same column may not, or they would be drawn over each other.
    """
    into: dict[Any, list] = {}
    for a, b in edges:
        into.setdefault(b, []).append(a)
    at: dict[Any, int] = {}
    for L in sorted(nodes):
        taken: set[int] = set()
        # Ordered by where their parents are, so a fan-in does not cross itself: a node
        # whose sources are high up is drawn above one whose sources are lower down.
        for node in sorted(nodes[L],
                           key=lambda x: min((at[a] for a in into.get(x, ()) if a in at),
                                             default=0)):
            r = min((at[a] for a in into.get(node, ()) if a in at), default=0)
            while r in taken:
                r += 1
            at[node] = r
            taken.add(r)
    return at


# The four sides a cell's line may leave by, and the glyph for every combination of them.
# One table rather than a chain of conditions, because the cases that matter are the ones
# nobody thinks of: a horizontal crossing a vertical is `┼` and must not be either line
# winning, and a corner is a corner whether it was drawn by a fan-out or a fan-in.
LEFT, RIGHT, UP, DOWN = 1, 2, 4, 8
GLYPH = {
    LEFT: "─", RIGHT: "─", LEFT | RIGHT: "─",
    UP: "│", DOWN: "│", UP | DOWN: "│",
    RIGHT | DOWN: "┌", LEFT | DOWN: "┐", RIGHT | UP: "└", LEFT | UP: "┘",
    LEFT | RIGHT | DOWN: "┬", LEFT | RIGHT | UP: "┴",
    UP | DOWN | RIGHT: "├", UP | DOWN | LEFT: "┤",
    LEFT | RIGHT | UP | DOWN: "┼",
}


def _draw(nodes: dict, edges: list, layer: dict, row: dict, by_id: dict,
          bad: set) -> list[str]:
    """The grid, filled and joined: name cells in the columns, box-drawing in the gaps.

    A GAP IS ITS OWN LITTLE GRID, and this is the whole trick. Between two columns of
    names sits a block of character columns: two of horizontal stub, then ONE CHANNEL PER
    SOURCE in that gap, then the column the arrowheads live in. A source's line leaves its
    name, runs right to its own channel, turns down or up that channel to reach each of its
    targets' rows, and runs right again to the arrow. Because every source owns a channel,
    two fan-outs in one gap can never be mistaken for each other, and where one source's
    horizontal crosses another's vertical the table above draws the crossing as a crossing.

    Which is what makes the two shapes a plan actually has come out right:

        a ──┬→ b            a ──┬→ b ───┬→ d
            └→ c                └→ c ───┘

    Nothing here measures the pane. Rows are padded to their column's widest name so the
    gaps line up, and a line longer than the board is cut by the board, from the right,
    which loses the tail of a long chain rather than the start of every one of them.
    """
    cols = sorted(nodes)
    height = max(row.values(), default=0) + 1
    width = {L: max((_cell_w(n, by_id) for n in nodes[L]), default=0) for L in cols}
    where = {x: L for L, xs in nodes.items() for x in xs}
    out: list[list[str]] = [[] for _ in range(height)]
    for n, L in enumerate(cols):
        for r in range(height):
            here = next((x for x in nodes[L] if row[x] == r), None)
            out[r].append(_cell(here, by_id, width[L], bad))
        if n + 1 < len(cols):
            real = {row[x] for x in nodes[cols[n + 1]] if isinstance(x, str)}
            for r, piece in enumerate(_gap(edges, row, where, L, height, real)):
                out[r].append(piece)
    return [("".join(parts)).rstrip() for parts in out]


def _cell_w(node: Any, by_id: dict) -> int:
    """How wide a node's cell is, in COLUMNS. A placeholder takes no room of its own.

    `_visible_len` and not `len`, and it is the core's own — `switchboard/board.py` fixed
    this exact bug once and says why there: "measuring in characters is the bug this whole
    section exists to close". One CJK ideograph is two columns, so a name counted in
    characters and drawn in columns puts every connector in this gap somewhere other than
    where the name ends, and the whole flowchart below it stops lining up.
    """
    return 0 if not isinstance(node, str) else _visible_len(_label(by_id[node]))


def _cell(node: Any, by_id: dict, width: int, bad: set) -> str:
    """One column cell: a painted name padded to the column, a line through, or air.

    A COLUMN IS ITS WIDEST NAME PLUS TWO, and the two are the air either side of a name.
    They live here rather than in the connector block because a placeholder has to fill
    them with `─` — a long edge crossing this column must arrive and leave as one
    unbroken line, and a gap of one space at each end of it would read as two edges.

    A placeholder is drawn as the line it stands for, which is the point of having
    invented it: a long edge passes through this column visibly, at the row it was given,
    instead of being routed around the picture or dropped.
    """
    if node is None:
        return " " * (width + 2)
    if not isinstance(node, str):
        return "─" * (width + 2)
    name = _label(by_id[node])
    return (" " + _paint(name, by_id[node].get("progress"), node in bad)
            + " " * (width - _visible_len(name)) + " ")


def _label(step: dict) -> str:
    """A step's name as the chart draws it: its DISPLAY name, flattened, never empty.

    The `display` first and the `name` behind it, because that is the whole reason `display`
    exists — a cell in a flowchart is a handful of columns and a step's full name is a
    sentence, so a step authored with a short board label draws it and one without falls back
    to the name. Resolved upstream (`_resolve`), so a named step's `display` is already its
    definition's by the time this sees it.

    NOTHING IS CLIPPED HERE ANY MORE, and that is the point of display names being required
    rather than optional. The old per-cell clip at 22 columns was what produced a column of
    half-sentences — `Investigate: find the…` — because the fallback it clipped was the full
    name, and the clipped half was the informative half. A display name is short because its
    author made it short; there is no length a renderer can pick that is better than that
    judgement, and a name too long for the pane now costs the tail of ONE line rather than
    the meaning of every cell. The board's own clip, from the right, is the only one left.

    `_flat` either way, which is what keeps this file's own colour the only escape sequence in
    a line the seam is asked to carry. An unnamed step is `?` rather than a blank cell — a
    node with nothing in it looks like a bug in the chart, and it is a bug in the plan.
    """
    return _flat(step.get("display") or step.get("name") or "") or "?"


def _paint(name: str, progress: Any, bad: bool = False) -> str:
    """A name in its progress's colour, or plain. See `GREEN`/`GREY`/`YELLOW` above.

    `bad` WINS over every progress colour, and it has to: a step missing its display name
    or its dep is drawn wrong wherever it is drawn, and a done step in green would say the
    one thing about it that is going well. Red is the defect, and the progress of a step
    nobody can read is not the question.
    """
    if bad:
        return RED + name + PLAIN
    p = str(progress or "")
    if p == OPEN:
        return name
    if p == DONE:
        return GREEN + name + PLAIN
    if p == SKIPPED:
        return GREY + name + PLAIN
    return YELLOW + name + PLAIN


def _gap(edges: list, row: dict, where: dict, left: int, height: int,
         real: set) -> list[str]:
    """The block of connectors between two columns, as one string per row.

    SOURCES THAT GO TO THE SAME PLACES SHARE A CHANNEL, which is the difference between
    a fan-in that reads and one that does not. Four steps all feeding `ship` are four
    lines converging on one point, and four channels draws them as `┬┬┬` — three of which
    say nothing, because the lines never diverge. One shared channel draws the same four
    edges as `┬ ├ ├ ┘`, which is the shape somebody actually recognises.

    Beyond that, channels go in ROW ORDER, top group leftmost. That is what makes a
    diamond close cleanly: the edge with furthest to travel vertically gets the channel
    nearest the targets, so it turns last and crosses least.

    HOW LONG THE ARROWS ARE is `STUB` and nothing else here: a plain hop is that many
    dashes plus its arrowhead, and everything below counts the stub through the constant
    rather than through the literal it used to be in these two places.
    """
    out: dict[Any, set] = {}
    for a, b in edges:
        if where.get(a) == left:
            out.setdefault(a, set()).add(row[b])
    if not out:
        return [" "] * height
    # Grouped on the set of rows an edge lands in, so two sources merge only when the
    # picture would draw them as one bundle anyway.
    bundles: dict[frozenset, list] = {}
    for a, targets in out.items():
        bundles.setdefault(frozenset(targets), []).append(a)
    order = sorted(bundles, key=lambda t: min(row[a] for a in bundles[t]))

    span = STUB + len(order) + 1                # stub, one channel each, arrowheads
    grid = [[0] * span for _ in range(height)]
    head: dict[int, bool] = {}                  # row -> is what it points at a real step?

    def mark(r: int, c: int, side: int) -> None:
        grid[r][c] |= side

    for k, targets in enumerate(order):
        ch = STUB + k
        srows = [row[a] for a in bundles[targets]]
        for sr in srows:                        # out of each name, across to the channel
            for c in range(0, ch):
                mark(sr, c, LEFT | RIGHT)
            mark(sr, ch, LEFT)
        lo, hi = min(srows + list(targets)), max(srows + list(targets))
        for r in range(lo, hi + 1):             # the channel itself
            if r > lo:
                mark(r, ch, UP)
            if r < hi:
                mark(r, ch, DOWN)
        for tr in targets:                      # the channel across to the arrowhead
            mark(tr, ch, RIGHT)
            for c in range(ch + 1, span - 1):
                mark(tr, c, LEFT | RIGHT)
            head[tr] = tr in real

    # An arrowhead only where a real step is being pointed at. An edge merely PASSING
    # through this column lands on a placeholder, and `→─────` in the middle of one line
    # reads as two edges meeting rather than as the single long one it is.
    return ["".join(GLYPH.get(cell, " ") for cell in grid[r][:-1])
            + ("→" if head.get(r) else "─" if r in head else " ")
            for r in range(height)]


class _Rows(_Live):
    """`_Live` with its one question already answered — off the rows the board handed in.

    `_Live.agents()` is the single place that costs a subprocess, and everything else in
    that class is derivation on top of it. Overriding it is therefore the whole of what
    this file has to do to be free: `owner()` and `condition()` are inherited unchanged,
    so the board reads a dead owner and an abandoned plan by exactly the rules `show`
    does, including the ones that matter most — a snapshot that did not arrive says
    nothing about anybody, and `unknown` is never `dead`.

    A dict per row, not the row itself, because `_Live` reads its rows as `sb status`
    JSON. Four keys, which is every field it looks at. `display_state` is the store's own
    reconciliation of the state column against what the pane is doing and is passed
    through rather than re-derived — the same contract `_Live.owner` relies on.

    A COLLAPSED ROW IS COUNTED, not dropped, and that is the one place this class had to
    do more than hand its rows over. `status.Collapsed` stands in for a whole archived
    subtree and carries no agent — but archived is what every agent on a worktree looks
    like after `sb cleanup`, which is the ordinary end of a job and precisely when a human
    glances at the board. Dropping those rows left `agents()` empty, and `condition()`
    reads empty as "no agent was ever here" and answers `live`: a plan whose every agent
    was cleaned up drew as live on the board while `sb plugin plans list`/`show`, which
    ask `sb status` and see the archived rows themselves, said `dormant` about the same
    plan at the same instant. The board must not disagree with `show` about one record.

    So a collapsed row contributes `count` closed agents in its own workspace, which is
    what the seam hands over and all it hands over. Closed and not unknown: what a
    collapse stands for is a finished delegation, and `sb cleanup` only takes rows that
    ended. The residue is an agent archived while its state was still open — a blocked
    agent whose pane died — which this reads as dormant where `show` would still say live.
    That is a narrower disagreement than the one it replaces and it corrects itself the
    moment the row is restored or the state is written.

    A `workspace` of None is the seam saying the hidden agents were in more than one, and
    those are counted for nobody: `condition` matches on the plan's workspace name, so an
    unattributable row is not evidence about this plan and is not made into some.
    """

    # Not an agent name and not able to become one: `switchboard/validate.py`'s
    # `AGENT_NAME` starts at `[a-z]`, so a synthetic key can never shadow a real row in
    # `_Live.owner`'s lookup by name. Only `condition` ever looks at these, and it looks
    # at values.
    ARCHIVED = "+archived-%d"

    def __init__(self, rows: list) -> None:
        agents: dict[str, Any] = {}
        for r in rows:
            name = getattr(r, "name", None)
            if name and hasattr(r, "state"):
                agents[str(name)] = {"state": getattr(r, "state", None),
                                     "display_state": getattr(r, "display_state", None),
                                     "gone": getattr(r, "gone", False),
                                     "workspace": getattr(r, "workspace", None)}
                continue
            count = getattr(r, "count", None)
            if hasattr(r, "state") or not isinstance(count, int):
                continue                        # not an agent row and not a collapse
            ws = getattr(r, "workspace", None)
            for _ in range(max(count, 0)):
                agents[self.ARCHIVED % len(agents)] = {
                    "state": CLOSED[0], "display_state": None,
                    "gone": False, "workspace": ws}
        self._agents: Any = agents

    def agents(self) -> dict:
        """The board's own rows, and never a question. See the class docstring.

        A dict and never None, which is a claim `_Live` reads as "sb answered": it did,
        and the collector is who it answered. The rows are scoped to ONE worktree, which
        is the group being drawn — and `condition` only ever counts agents whose
        `workspace` matches the plan's, so a plan on this worktree is judged against
        exactly the agents on it.
        """
        return self._agents
