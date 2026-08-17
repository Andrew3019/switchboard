#!/usr/bin/env python3
"""The mechanical half of the analysis pass: read the plan records, count, propose.

`SKILL.md` beside this file is the other half — the agent that reads what this prints and
turns candidates into proposals worth putting to a human. This file exists because three
lines of the behavioural contract are promises a prose instruction cannot keep. An agent
told "name your bias every time" names it most times; an agent told "tell the two kinds of
rework apart" is being asked to infer from a changelog it half-read. So the bias sentence,
the abandoned flags and the split between rework-as-try-count and rework-as-added-step are
computed here, where they are either in the output or the tests fail.

READ ONLY, structurally
-----------------------

Nothing here opens a file for writing, imports the plugin, or runs any sb verb but one.
`SB_ARGV` is a constant and the only argv this file ever hands a subprocess: `plugin plans
list --all --json`, which mutates nothing. There is no code path that takes a verb from an
argument, and a test pins that. That is the whole of "it only proposes; it never edits" —
not a rule the reader is asked to keep, but the absence of anything that could break it.

The records are read through the plugin's own read surface rather than by re-parsing
`plans.json`, so this cannot drift from the format. What `list --all --json` hands back is
already resolved — a named step carries the library's words, and every plan carries the
`condition` and `worktree` PR4 derives at read time and stores nowhere. Deriving those here
a second time is how the two answers start disagreeing.

The two kinds of rework
-----------------------

The design says a lead redoing work either re-enters the step, which leaves a try count, or
adds a step for the fix, which leaves something that looks like a recurring pattern —
and that the analysis pass can tell them apart because the changelog records which happened.
So they are read off the changelog ACTIONS (`rework` vs `add-step`) and never off the step,
and they are never added together. `tries > 1` with no `rework` entry behind it is a third
thing again — a hand-edited record — and is reported as that rather than folded into either.

What is excluded, and why the bias is stated anyway
--------------------------------------------------

A plan whose worktree is gone with steps still open reads as `abandoned`, and the design
says plainly what happens if that is missed: every job that fell apart is read as a job that
went well. So abandoned plans are listed first, before anything else, and a proposal
supported only by abandoned or unreadable plans is marked weak rather than dropped — what
derailed is worth reading, it is just not evidence that anything worked.

That is a mechanical fix for a mechanical half of the bias. The other half cannot be fixed
here at all: ticking and note-writing are voluntary acts by an agent still on top of its
job, so a run that derails stops being written down and never reaches this file in any
condition. Hence `BIAS`, which is in every output this file produces — head of the human
report, foot of it, and a top-level key in the JSON.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any, Iterable, Optional

# The one command this file runs, as a constant so there is nothing to inject into. `--all`
# because the pass reads the whole repo's history and not the worktree it happens to stand
# in; `list` because it returns every plan resolved and with its condition derived, which
# is the same view `show` gives one plan at a time.
SB_ARGV = ("plugin", "plans", "list", "--all", "--json")

# Said in every output. Not a footnote: the design's known limitations concede that the
# record is thinnest in exactly the runs this pass exists to find, and a reader who forgets
# that reads a survey of the jobs that went well as a survey of the work.
BIAS = ("Read this as biased toward jobs that went well: ticking and note-writing are "
        "voluntary acts by an agent still on top of its job, so a run that derailed is "
        "thin or absent here. Absence of a pattern is not evidence it does not recur.")

# The two progress words the lifecycle verbs write. `progress` is an OPEN vocabulary in the
# plugin — a lead may park a step in `waiting on Andrew` — so these are used to recognise a
# step that is CLOSED and never to validate one. Anything else is open as far as this file
# is concerned, which is the reading that keeps a parked step visible.
DONE, SKIPPED = "done", "skipped"

# PR4's vocabulary for a plan's condition, derived at read time and stored nowhere.
LIVE, DORMANT, FINISHED, ABANDONED, UNSURE = (
    "live", "dormant", "finished", "abandoned", "unknown")

# The conditions that are evidence of a job that RAN TO A SHAPE. `live` and `dormant` are
# in flight — counted, but a pattern in them may still change before the job ends.
COMPLETE = (FINISHED,)
INFLIGHT = (LIVE, DORMANT)

# How many plans a pattern has to appear in before it is worth proposing. Two, because the
# catalogue is meant to grow from use and the corpus starts almost empty — a threshold that
# waits for five says nothing for the first six months, which is when this is most useful.
RECURS = 2


# -- reading -------------------------------------------------------------------


def records(sb: str = "sb", *, source: Optional[str] = None) -> list[dict]:
    """Every plan in the repo, as the plugin renders it. From sb, or from captured JSON.

    `source` is a file (or `-` for stdin) holding what `sb plugin plans list --all --json`
    printed earlier — for analysing a corpus captured elsewhere, and for the tests, which
    have synthetic records and no store to put them in. Either way the shape is the
    plugin's own output and never a re-parse of `plans.json`.
    """
    if source is not None:
        text = sys.stdin.read() if source == "-" else open(source, encoding="utf-8").read()
    else:
        out = subprocess.run([sb, *SB_ARGV], capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError(
                f"`{sb} {' '.join(SB_ARGV)}` failed ({out.returncode}): "
                f"{(out.stderr or out.stdout).strip()[:400]}")
        text = out.stdout
    return _plans(json.loads(text))


def _plans(payload: Any) -> list[dict]:
    """The plan list out of whatever the read surface returned.

    Three shapes are accepted and no more: sb's `--json` envelope, the bare `data` list
    inside it, and one plan on its own (what `show --json` gives). Anything else is a
    refusal naming what arrived, because guessing at an unfamiliar shape is how a survey
    ends up reporting confidently on nothing.
    """
    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or any(not isinstance(p, dict) for p in payload):
        raise ValueError("not a plans listing: expected sb's --json envelope, its `data` "
                         f"list, or one plan object; got {type(payload).__name__}")
    return payload


# -- the survey ----------------------------------------------------------------


def survey(plans: Iterable[dict]) -> dict:
    """Everything the records say, counted. Proposals are built from this and nothing else.

    Structured rather than prose so that `report()` and a machine reader see the same
    findings, and so a later pass can diff two surveys without re-deriving them.
    """
    plans = list(plans)
    corpus = _corpus(plans)
    rework = _rework(plans)
    catalogue = _catalogue(plans)
    out = {"bias": BIAS, "corpus": corpus, "rework": rework, "catalogue": catalogue,
           "gaps": _gaps(plans, rework)}
    out["proposals"] = _proposals(plans, out)
    return out


def _corpus(plans: list[dict]) -> dict:
    """What was read, split by condition, with the ones that must not be read as successes.

    A plan with no `condition` is `unknown` here rather than assumed fine: the field is
    derived by the plugin at read time, so its absence means this came from somewhere that
    did not derive it, which is exactly the case where a guess would be wrong.
    """
    by: dict[str, list[str]] = {}
    for p in plans:
        by.setdefault(_condition(p), []).append(_pid(p))
    return {"plans": len(plans),
            "by_condition": {k: sorted(v) for k, v in sorted(by.items())},
            "abandoned": [_flag(p) for p in plans if _condition(p) == ABANDONED],
            "unreadable": [_flag(p) for p in plans if _condition(p) == UNSURE],
            "complete": sorted(_pid(p) for p in plans if _condition(p) in COMPLETE),
            "in_flight": sorted(_pid(p) for p in plans if _condition(p) in INFLIGHT)}


def _flag(plan: dict) -> dict:
    """One plan that must not be read as a success, with what is left open on it."""
    open_steps = [s for s in _steps(plan) if _progress(s) not in (DONE, SKIPPED)]
    return {"plan": _pid(plan), "title": plan.get("title") or "",
            "condition": _condition(plan),
            "worktree": plan.get("worktree") or "unknown",
            "steps": len(_steps(plan)),
            "open": [f"{s.get('id')} {_name(s)}".strip() for s in open_steps],
            "last_entry": _last(plan)}


def _rework(plans: list[dict]) -> dict:
    """The two kinds of rework, read off the changelog and never added together.

    `rework` entries are a step re-entered — the try count went up and the shape of the
    plan did not change. `add-step` entries are a step invented mid-job — the shape DID
    change, and a run of them under the same name is what a missing library step looks
    like. The design says a lead adding a step for rework says so in the changelog, so the
    reason is carried through here rather than summarised away: it is the only thing that
    says which of the two a given `add-step` was.

    `unexplained_tries` is the third case and is not either of them: a step whose `tries`
    is above 1 with no `rework` entry behind it did not get there through a verb, so it is
    reported as a record that was edited by hand rather than counted as rework that
    happened.
    """
    tries: list[dict] = []
    added: list[dict] = []
    unexplained: list[dict] = []
    for p in plans:
        counted: dict[str, int] = {}
        for e in _changelog(p):
            action = str(e.get("action") or "")
            if action == "rework":
                sid = _sid(e)
                counted[sid] = counted.get(sid, 0) + 1
                tries.append({"plan": _pid(p), "step": sid, "key": _key(p, sid),
                              "reason": e.get("reason"), "detail": e.get("detail"),
                              "by": e.get("by"), "condition": _condition(p)})
            elif action == "add-step":
                sid = _sid(e)
                added.append({"plan": _pid(p), "step": sid, "key": _key(p, sid),
                              "name": _named(p, sid) or _tail(e.get("detail")),
                              "reason": e.get("reason"), "by": e.get("by"),
                              "condition": _condition(p)})
        for s in _steps(p):
            n = s.get("tries")
            n = n if isinstance(n, int) else 1
            if n > 1 and not counted.get(str(s.get("id") or "")):
                unexplained.append({"plan": _pid(p), "step": s.get("id"),
                                    "name": _name(s), "tries": n})
    return {"by_try_count": tries, "by_added_step": added,
            "unexplained_tries": unexplained,
            "counts": {"try_count_entries": len(tries),
                       "added_step_entries": len(added),
                       "steps_reworked": len({(t["plan"], t["step"]) for t in tries}),
                       "note": "Never summed: a bumped try count and an added step are "
                               "different signals about the same job."}}


def _catalogue(plans: list[dict]) -> dict:
    """What the catalogue is actually used for, and what is being written by hand instead.

    A named step compares across plans because the name means the same thing wherever it
    appears; an on-the-fly step compares only as far as two leads happened to type the
    same words, which the design's known limitations say is not very far. Both are counted
    and the difference is stated wherever the count is shown.
    """
    named: dict[str, list[str]] = {}
    freehand: dict[str, list[str]] = {}
    skipped: dict[str, list[dict]] = {}
    templates: dict[str, list[str]] = {}
    for p in plans:
        for s in _steps(p):
            key = _defkey(s)
            (named if key else freehand).setdefault(
                key or _norm(_name(s)), []).append(_pid(p))
            if _progress(s) == SKIPPED:
                skipped.setdefault(key or _norm(_name(s)), []).append(
                    {"plan": _pid(p), "step": s.get("id"), "why": s.get("why")})
        for e in _changelog(p):
            if str(e.get("action") or "") == "template":
                templates.setdefault(_from(e.get("detail")), []).append(_pid(p))
    return {"named_steps": _tally(named), "freehand_steps": _tally(freehand),
            "skipped": {k: v for k, v in sorted(skipped.items())},
            "templates_used": _tally(templates),
            "note": "A named step compares across plans; a freehand one compares only as "
                    "far as two leads typed the same words. Granularity is a judgement "
                    "and step sets from different leads are not really comparable."}


def _tally(d: dict[str, list[str]]) -> list[dict]:
    """Counts, most-recurrent first, carrying the plans they came from rather than a number.

    The plan ids are the point: a proposal whose evidence is "5 times" cannot be checked,
    and one whose evidence is "p-3, p-7, p-9" can be read back by whoever is deciding.
    """
    return sorted(({"what": k, "plans": sorted(set(v)), "count": len(v)}
                   for k, v in d.items() if k),
                  key=lambda r: (-len(r["plans"]), -r["count"], r["what"]))


def _gaps(plans: list[dict], rework: dict) -> list[str]:
    """What the records could not answer — said out loud rather than guessed around.

    Reading cold only works if the record carries enough, and where it does not the honest
    output is a gap and not a quieter proposal. Nothing here writes a field to fix one:
    the schema belongs to the verbs, and a pass that grew the record would be editing it.
    """
    out = []
    if not plans:
        out.append("No plans were read at all — nothing here is a finding about the work.")
    thin = [_pid(p) for p in plans
            if not (p.get("notes") or []) and not any(s.get("notes") for s in _steps(p))]
    if thin:
        out.append(f"{len(thin)} plan(s) carry no notes at all ({_ids(thin)}) — their "
                   f"shape is readable and their story is not.")
    silent = [f"{t['plan']}/{t['step']}" for t in rework["by_try_count"] if not t["reason"]]
    if silent:
        out.append(f"{len(silent)} rework entr(ies) carry no reason ({_ids(silent)}) — "
                   f"the try count says work was redone and not what went wrong.")
    mute = [f"{a['plan']}/{a['step']}" for a in rework["by_added_step"] if not a["reason"]]
    if mute:
        out.append(f"{len(mute)} add-step entr(ies) carry no reason ({_ids(mute)}) — "
                   f"a step added for rework and a step that was simply missed look "
                   f"identical without one.")
    if rework["unexplained_tries"]:
        out.append(f"{len(rework['unexplained_tries'])} step(s) have a try count above 1 "
                   f"with no rework entry behind it — the record was edited outside the "
                   f"verbs, so neither kind of rework can be claimed for them.")
    return out


# -- proposals -----------------------------------------------------------------


def _proposals(plans: list[dict], s: dict) -> list[dict]:
    """Candidates, each with the plans it came from and what would weaken it.

    Candidates and not conclusions: this counts, and the agent reading `SKILL.md` decides
    which are worth putting to a human. Every one names the kind of catalogue addition it
    would be — the design's list is steps, templates, presets, roles, tooling and
    optimisations — so that a proposal that fits none of those is visibly a proposal about
    something else.
    """
    out: list[dict] = []
    by_id = {_pid(p): p for p in plans}

    for row in s["catalogue"]["freehand_steps"]:
        if len(row["plans"]) < RECURS:
            continue
        out.append(_p("library step", f"promote “{row['what']}” into the step library",
                      f"written by hand in {len(row['plans'])} plans; a named step is the "
                      f"part of a plan that compares across jobs, and this one is being "
                      f"retyped instead", row["plans"], by_id,
                      ["Two leads typing similar words is not the same as one step — read "
                       "the plans before promoting a name."]))

    added: dict[str, list[dict]] = {}
    for a in s["rework"]["by_added_step"]:
        added.setdefault(_norm(a["name"] or ""), []).append(a)
    for what, rows in sorted(added.items()):
        pids = sorted({r["plan"] for r in rows})
        if not what or len(pids) < RECURS:
            continue
        out.append(_p("step or template", f"a step for “{what}” is being added mid-job",
                      f"added after the plan was made in {len(pids)} plans — this is "
                      f"rework that CHANGED THE SHAPE of the plan, not a bumped try "
                      f"count, and a shape that keeps being repaired the same way belongs "
                      f"in the template it keeps missing from", pids, by_id,
                      [f"reasons given: {_reasons(rows)}",
                       "A step added for rework and a step simply forgotten are the same "
                       "action; the reason above is the only thing that separates them."]))

    hot: dict[str, list[dict]] = {}
    for t in s["rework"]["by_try_count"]:
        hot.setdefault(t["key"] or t["step"], []).append(t)
    for what, rows in sorted(hot.items()):
        pids = sorted({r["plan"] for r in rows})
        if len(rows) < RECURS:
            continue
        out.append(_p("optimisation or preset",
                      f"“{what}” is re-entered repeatedly",
                      f"{len(rows)} rework entries across {len(pids)} plan(s) — the step "
                      f"was redone in place, so the plan's shape was right and something "
                      f"about how it is run is not: a preset, a tighter brief or a "
                      f"different tool", pids, by_id,
                      [f"reasons given: {_reasons(rows)}",
                       "This is try-count rework and is deliberately not added to the "
                       "add-step count above."]))

    for row in s["catalogue"]["named_steps"]:
        skips = s["catalogue"]["skipped"].get(row["what"]) or []
        if len(skips) >= RECURS:
            out.append(_p("catalogue review",
                          f"the library step “{row['what']}” is usually skipped",
                          f"skipped {len(skips)} times out of {row['count']} uses — either "
                          f"the definition is wrong for these jobs or it is obliged where "
                          f"it does not belong",
                          sorted({k["plan"] for k in skips}), by_id,
                          [f"reasons given: {_reasons(skips, 'why')}",
                           "A skip is a state with a reason; read them before changing a "
                           "definition."]))

    shapes: dict[tuple, list[str]] = {}
    for p in plans:
        if _from_template(p):
            continue
        shape = tuple(sorted({_defkey(s) or _norm(_name(s)) for s in _steps(p)}))
        if len(shape) >= 3:
            shapes.setdefault(shape, []).append(_pid(p))
    for shape, pids in sorted(shapes.items()):
        if len(pids) < RECURS:
            continue
        out.append(_p("template", "the same plan is being built from scratch repeatedly",
                      f"{len(pids)} plans with no template behind them share the steps "
                      f"{', '.join(shape)}", pids, by_id,
                      ["A template is a copy and not a link — proposing one commits "
                       "nothing about the plans that already exist."]))
    return out


def _p(kind: str, what: str, why: str, pids: list[str], by_id: dict, caveats: list) -> dict:
    """One proposal, with the plans behind it and how far they can be leaned on.

    `strength` is where the abandoned flag does its work. A pattern seen only in plans that
    fell apart is not evidence that anything worked, so it is marked `weak` and kept rather
    than dropped: what derailed is worth reading, it is just a different claim.
    """
    conds = [_condition(by_id[i]) for i in pids if i in by_id]
    solid = [c for c in conds if c in COMPLETE or c in INFLIGHT]
    if not solid:
        strength, note = "weak", ("every plan behind this is abandoned or unreadable — "
                                  "read as what derailed, never as what worked")
    elif len(solid) < len(conds):
        strength, note = "mixed", ("some plans behind this are abandoned or unreadable "
                                   "and are not evidence that anything worked")
    elif all(c in INFLIGHT for c in conds):
        strength, note = "provisional", "every plan behind this is still running"
    else:
        strength, note = "supported", "backed by plans that ran to a shape"
    return {"kind": kind, "propose": what, "because": why, "strength": strength,
            "evidence": {"plans": pids,
                         "conditions": {i: _condition(by_id[i]) for i in pids if i in by_id}},
            "caveats": [note, *caveats, BIAS]}


# -- rendering -----------------------------------------------------------------


def report(s: dict) -> str:
    """The survey as a page to read. The bias sentence opens it and closes it.

    Abandoned plans come before the proposals rather than after, because a reader who
    reaches the proposals first has already started counting derailed jobs as evidence.
    """
    L = [f"BIAS — {s['bias']}", ""]
    c = s["corpus"]
    L.append(f"Read {c['plans']} plan(s): " + (", ".join(
        f"{k} {len(v)}" for k, v in c["by_condition"].items()) or "none"))
    L.append("")
    L.append("ABANDONED — not to be read as jobs that went well")
    if c["abandoned"]:
        for f in c["abandoned"]:
            L.append(f"  {f['plan']}  {f['title']}  ({len(f['open'])} step(s) still open: "
                     f"{', '.join(f['open']) or '—'}); last entry {f['last_entry']}")
    else:
        L.append("  (none in this corpus — which is itself a claim the bias above weakens)")
    if c["unreadable"]:
        L.append("UNREADABLE — condition could not be derived; excluded from every claim")
        for f in c["unreadable"]:
            L.append(f"  {f['plan']}  {f['title']}")
    L.append("")

    r = s["rework"]
    L.append("REWORK — two kinds, from the changelog, never added together")
    L.append(f"  as try count (step re-entered, shape unchanged): "
             f"{r['counts']['try_count_entries']} entr(ies) over "
             f"{r['counts']['steps_reworked']} step(s)")
    for t in r["by_try_count"]:
        L.append(f"    {t['plan']}/{t['step']}  {t['key']}  — {t['reason'] or 'no reason given'}")
    L.append(f"  as added step (shape changed mid-job): "
             f"{r['counts']['added_step_entries']} entr(ies)")
    for a in r["by_added_step"]:
        L.append(f"    {a['plan']}/{a['step']}  {a['name']}  — {a['reason'] or 'no reason given'}")
    for u in r["unexplained_tries"]:
        L.append(f"  neither: {u['plan']}/{u['step']} has tries={u['tries']} with no "
                 f"rework entry — record edited outside the verbs")
    L.append("")

    L.append("PROPOSALS — proposed only; nothing here has been changed")
    if not s["proposals"]:
        L.append("  (nothing recurs often enough yet — say so rather than inventing one)")
    for p in s["proposals"]:
        L.append(f"  [{p['kind']}, {p['strength']}] {p['propose']}")
        L.append(f"      because {p['because']}")
        conds = p["evidence"]["conditions"]
        cited = ", ".join("{} ({})".format(i, conds.get(i, "?"))
                          for i in p["evidence"]["plans"])
        L.append(f"      from {cited}")
        for cav in p["caveats"][:-1]:
            L.append(f"      caveat: {cav}")
    L.append("")

    if s["gaps"]:
        L.append("WHAT THE RECORD COULD NOT ANSWER")
        for g in s["gaps"]:
            L.append(f"  {g}")
        L.append("")
    L.append(f"BIAS — {s['bias']}")
    return "\n".join(L)


# -- small readers -------------------------------------------------------------
#
# Everything below is defensive in one direction: a record that is missing a field, or
# holding a type nothing here expected, produces a blank or an `unknown` and never an
# exception. The corpus is kept forever and includes plans written by every version of the
# plugin there has ever been, so a survey that dies on one malformed row is a survey that
# stops working exactly as the history gets long enough to be worth reading.


def _pid(p: dict) -> str:
    return str(p.get("id") or "?")


def _condition(p: dict) -> str:
    return str(p.get("condition") or UNSURE)


def _steps(p: dict) -> list[dict]:
    v = p.get("steps")
    return [s for s in v if isinstance(s, dict)] if isinstance(v, list) else []


def _changelog(p: dict) -> list[dict]:
    v = p.get("changelog")
    return [e for e in v if isinstance(e, dict)] if isinstance(v, list) else []


def _progress(s: dict) -> str:
    return str(s.get("progress") or "")


def _name(s: dict) -> str:
    return str(s.get("name") or s.get("def") or "").strip()


def _defkey(s: dict) -> str:
    k = s.get("def")
    return str(k).strip() if k else ""


def _key(p: dict, sid: str) -> str:
    """What a step is, for counting: its library key if it has one, else its words."""
    for s in _steps(p):
        if str(s.get("id") or "") == sid:
            return _defkey(s) or _norm(_name(s))
    return sid


def _named(p: dict, sid: str) -> str:
    for s in _steps(p):
        if str(s.get("id") or "") == sid:
            return _name(s)
    return ""


def _sid(e: dict) -> str:
    """The step id out of a changelog entry's detail — `s-3 …` is how every verb writes it.

    The one place this file parses a rendered string rather than reading a field, and it is
    not a choice: a changelog entry carries `action`, `by`, `reason` and `detail`, and the
    step an entry is about is only ever inside the last of those. Every verb that touches a
    step opens its detail with the id, so this holds for anything the plugin wrote — but a
    detail format that changes silently breaks the rework split, which is the strongest
    argument for the entry carrying the step id as a field of its own. Not added here: the
    schema belongs to the verbs, and this pass does not edit.
    """
    m = re.match(r"\s*(s-\d+)", str(e.get("detail") or ""), re.IGNORECASE)
    return m.group(1).lower() if m else "?"


def _tail(detail: Any) -> str:
    """An `add-step` detail is `s-4 <the name>`; the name is what is left after the id."""
    return re.sub(r"^\s*s-\d+\s*", "", str(detail or ""), flags=re.IGNORECASE).strip()


def _from(detail: Any) -> str:
    """A `template` detail opens `from <name>:` — which template a plan was copied from."""
    m = re.match(r"\s*from\s+([^:]+):", str(detail or ""))
    return m.group(1).strip() if m else ""


def _from_template(p: dict) -> bool:
    return any(str(e.get("action") or "") == "template" for e in _changelog(p))


def _last(p: dict) -> str:
    log = _changelog(p)
    return f"{log[-1].get('action')} by {log[-1].get('by')}" if log else "none"


def _norm(text: str) -> str:
    """A step's words, flattened enough that two leads typing the same thing land together.

    Case and spacing only. Nothing stems, drops words or matches fuzzily: the design says
    step sets from different leads are not really comparable, and a matcher that tried
    harder would manufacture the comparability the design says is not there.
    """
    return re.sub(r"\s+", " ", str(text or "").strip().lower()).strip(" .;:—-")


def _reasons(rows: list[dict], field: str = "reason") -> str:
    seen = [str(r.get(field)).strip() for r in rows if r.get(field)]
    return "; ".join(dict.fromkeys(seen)) or "none given"


def _ids(xs: list[str], limit: int = 8) -> str:
    return ", ".join(xs[:limit]) + (f", … (+{len(xs) - limit})" if len(xs) > limit else "")


# -- entry point ---------------------------------------------------------------


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Read the saved plan records and propose catalogue additions. "
                    "Reads only: this never writes a plan, a definition or a template.")
    ap.add_argument("--sb", default="sb", help="the sb to ask (default: sb on PATH)")
    ap.add_argument("--input", help="a captured `plans list --all --json`, or - for stdin")
    ap.add_argument("--json", action="store_true", help="the survey as JSON")
    args = ap.parse_args(argv)
    try:
        plans = records(args.sb, source=args.input)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"analysis: {e}", file=sys.stderr)
        return 2
    s = survey(plans)
    print(json.dumps(s, indent=2) if args.json else report(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
