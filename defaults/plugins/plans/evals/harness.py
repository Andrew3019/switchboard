#!/usr/bin/env python3
"""The mechanical half of the evaluation pass: capture the context, check the names.

`SKILL.md` beside this file is the other half — the runbook a person drives the pass from,
and `RUBRIC.md` is what the judge scores against. This file exists for the two claims in
that pass that a prose instruction cannot keep on its own:

  manifest   what the planner was actually given — its instruction, the generated
             catalogue, its brief, the repo's model configuration and the capability seed
             it was spawned with. Hashed, so two runs can be compared rather than
             described.
  check      every catalogue name a produced plan uses that this repo's generated
             catalogue does not have. "Invents no catalogue entries" is a success
             criterion, and a criterion nobody can compute is an opinion.

DEVELOPMENT ONLY. Nothing here is an `sb` verb, nothing imports switchboard, and nothing in
the plugin loads this file. It is a script in a directory beside a plugin, run by hand.

READ ONLY, STRUCTURALLY
-----------------------

`SB_READS` holds every argv this file will ever hand a subprocess, as a constant. Each is a
read: `plugin plans planner`, `plugin plans guide`, `plugin plans catalog --json`, `models
--json`, `inspect <agent> --json` and `plugin plans show <plan> --json`. Two of them carry a
NAME hole, `{agent}` and `{plan}`, and `_argv` fills exactly those two and nothing else — a
caller cannot reach the verb words, because they are never taken from an argument. A test
pins that.

WHAT THE CHECK OWNS, AND WHAT IT DOES NOT
-----------------------------------------

A plan holds catalogue names in two kinds of place, and they are not equally checkable.

STRUCTURED slots are exact and the check is exact on them: a step's `def` is a library step
name and `strategy.resources.presets` are preset names. An unknown name in one of those is
an invented catalogue entry and the check says so.

`strategy.model` is deliberately NOT one of them. The planner is instructed that qualitative
advice — "strong and fresh for review" — is free text and does not come from the catalogue,
so a word in that field is not a name anybody claimed exists. The field is read for tier
names it does mention, as evidence, and an invented tier is caught in the positions where
the idiom is unambiguous instead: `--model x`, and "the `x` tier".

PROSE is not enumerable, so the check reads only the POSITIONS where the repo's own idiom
puts a catalogue name — `--role x`, `--model x`, `held x`, "the `x` preset", and the handful
of `sb` subcommands that take a catalogue name as their argument. That catches the realistic
invention and it is not complete. A name invented in free prose outside those positions is
the judge's to spot, and `RUBRIC.md` says so rather than leaving the reader to assume the
mechanical check covered it.

`strategy.resources.skills` and `.tools` are reported and never checked. The catalogue says
in as many words that skills and tools are not in it — they come from the session an agent
runs in — so there is nothing to check them against, and marking them ungrounded would be
this file inventing a rule the catalogue does not have.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from typing import Any, Iterable, Optional

# Every argv this file runs, as a constant. All six are reads. `{agent}` and `{plan}` are
# the only holes, and `_argv` is the only thing that fills them.
SB_READS: dict[str, tuple[str, ...]] = {
    "planner": ("plugin", "plans", "planner"),
    "guide": ("plugin", "plans", "guide"),
    "catalog": ("plugin", "plans", "catalog", "--json"),
    "models": ("models", "--json"),
    "inspect": ("inspect", "{agent}", "--json"),
    "plan": ("plugin", "plans", "show", "{plan}", "--json"),
}

# The one part of the manifest that is not mechanical, said the same way every time it is
# printed. No sb command reports the skills or tools available to a session: they come from
# the harness the agent runs in. So this half is a self-report, and it is exempt from the
# reproducibility the rest of the manifest has — by construction, not by omission.
SELF_REPORT = ("skills and tools are a marked SESSION SELF-REPORT: no sb command reports "
               "them, so they are not reproducible from this repo and are exempt from the "
               "determinism the rest of this manifest has")

# Where the repo's own prose puts a catalogue name. Precision over recall on purpose: a
# pattern that fired on ordinary words would bury the real findings in noise, and the
# judge covers the residual.
PROSE = (
    (r"--role\s+`?([A-Za-z][\w.\-]*)", "roles"),
    (r"--model\s+`?([A-Za-z][\w.\-]*)", "models"),
    (r"--with\s+`?(@?[\w.\-]+)", "presets"),
    (r"\bsb\s+presets\s+`?([\w.\-]+)", "presets"),
    (r"\bsb\s+roles\s+`?([\w.\-]+)", "roles"),
    (r"\bsb\s+plugin\s+plans\s+library\s+`?([\w.\-]+)", "library"),
    (r"\bsb\s+plugin\s+plans\s+template\s+use\s+`?([\w.\-]+)", "templates"),
    (r"\bsb\s+grant\s+\S+\s+`?([\w.\-]+)", "capabilities"),
    (r"\b(?:held|delegable)\s+`([\w.\-]+)`", "capabilities"),
    (r"`([\w.\-]+)`\s+(?:role|preset|tier|template)\b", None),
)

# `strategy.model` is free text BY INSTRUCTION — the planner is told that qualitative advice
# ("strong and fresh for review") does not come from the catalogue and is not meant to. So
# that field is read for tier names it DOES mention, as evidence for the report, and no
# attempt is made to decide that a word in it was meant to be a tier and was invented. An
# invented tier is caught where the idiom is unambiguous: `--model x`, and "the `x` tier".
WORDS = re.compile(r"[\w.\-]+")


# -- reading -------------------------------------------------------------------


def _argv(key: str, **holes: str) -> list[str]:
    """One of `SB_READS`, with its name holes filled and nothing else touched.

    The verb words come from the constant every time. `holes` reaches only `{agent}` and
    `{plan}`, and an unfilled hole is a programming error rather than a shell argument
    that happens to start with a dash.
    """
    out = []
    for word in SB_READS[key]:
        if word.startswith("{") and word.endswith("}"):
            name = word[1:-1]
            if name not in holes:
                raise KeyError(f"{key} needs {word}")
            out.append(str(holes[name]))
        else:
            out.append(word)
    return out


def _run(sb: str, key: str, **holes: str) -> str:
    out = subprocess.run([sb, *_argv(key, **holes)], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"`{sb} {' '.join(_argv(key, **holes))}` failed "
                           f"({out.returncode}): {(out.stderr or out.stdout).strip()[:400]}")
    return out.stdout


def _payload(text: str) -> Any:
    """The `data` out of sb's `--json` envelope, or the document itself if it has none.

    `sb models --json` prints a bare object; the plugin's commands print an envelope. Both
    are read the same way rather than by remembering which is which.
    """
    doc = json.loads(text)
    if isinstance(doc, dict) and "ok" in doc and "data" in doc:
        return doc["data"]
    return doc


def _digest(text: str) -> dict:
    """A hash and a size, so two runs compare instead of being described."""
    return {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "chars": len(text), "lines": text.count("\n") + (1 if text else 0)}


def catalogue(sb: str = "sb", *, source: Optional[str] = None) -> dict:
    if source is not None:
        return _payload(_read_file(source))
    return _payload(_run(sb, "catalog"))


def plan(pid: str, sb: str = "sb", *, source: Optional[str] = None) -> dict:
    if source is not None:
        return _payload(_read_file(source))
    return _payload(_run(sb, "plan", plan=pid))


def _read_file(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# -- the catalogue as a set of names -------------------------------------------


def names(cat: dict) -> dict[str, set[str]]:
    """The generated catalogue reduced to the names a plan may use, by category.

    Presets include the `@plugin` fragments bound to every agent, because a plan naming
    `@plans` is naming something the catalogue lists — just under a different key.
    """
    presets = cat.get("presets") or {}
    return {
        "roles": {r["name"] for r in cat.get("roles") or []},
        "models": {t["name"] for t in ((cat.get("models") or {}).get("tiers") or [])},
        "presets": set(presets.get("available") or []) | set(presets.get("every_agent") or []),
        "plugins": set(cat.get("plugins") or []),
        "capabilities": set(cat.get("capabilities") or []),
        "library": {s["name"] for s in cat.get("library") or []},
        "templates": {t["name"] for t in cat.get("templates") or []},
    }


def _known(known: dict[str, set[str]], name: str, category: Optional[str]) -> Optional[str]:
    """The category `name` belongs to, or None. `category=None` means try them all."""
    order = [category] if category else list(known)
    for cat in order:
        if name in known.get(cat, ()):
            return cat
    return None


# -- the grounding check -------------------------------------------------------


def _prose_of(step: dict) -> Iterable[tuple[str, str]]:
    """Every free-text field on a step, as (where, text)."""
    s = step.get("strategy") or {}
    for field in ("continuity", "orchestration", "model", "isolation", "verification",
                  "replan_if"):
        if isinstance(s.get(field), str):
            yield f"strategy.{field}", s[field]
    budget = s.get("budget") or {}
    for field in ("context", "passes"):
        if isinstance(budget.get(field), str):
            yield f"strategy.budget.{field}", budget[field]


def _claims(pl: dict, known: dict[str, set[str]]) -> list[dict]:
    """Every catalogue name the plan uses, with where it came from and how sure we are.

    `exact` claims are structured slots — an unknown name there is invented. `prose` claims
    are pattern matches in free text; an unknown name there is reported the same way,
    because these positions are the repo's own idiom and a miss in one is worth reading.
    """
    found: list[dict] = []
    seen: set[tuple] = set()

    def add(where, name, category, kind):
        name = (name or "").strip().strip("`.,;:)")
        if not name:
            return
        # Deduped on the POSITION and the name, not on how it was spotted: the same word
        # in the same field can match a structured read and a prose pattern both, and
        # printing it twice reads as two findings.
        key = (where, name, category)
        if key not in seen:
            seen.add(key)
            found.append({"where": where, "name": name, "category": category, "kind": kind})

    for step in pl.get("steps") or []:
        sid = step.get("id") or "?"
        if step.get("def"):
            add(f"{sid}.def", step["def"], "library", "exact")
        res = ((step.get("strategy") or {}).get("resources")) or {}
        for p in res.get("presets") or []:
            add(f"{sid}.strategy.resources.presets", p, "presets", "exact")
        model = ((step.get("strategy") or {}).get("model")) or ""
        for word in WORDS.findall(model):
            if word in known["models"]:
                add(f"{sid}.strategy.model", word, "models", "mention")
        for where, text in _prose_of(step):
            for pattern, category in PROSE:
                for hit in re.finditer(pattern, text):
                    add(f"{sid}.{where}", hit.group(1), category, "prose")
    return found


def check(pl: dict, cat: dict) -> dict:
    """The grounding report for one plan against one generated catalogue."""
    known = names(cat)
    grounded, ungrounded, seen = [], [], set()
    for claim in _claims(pl, known):
        where = _known(known, claim["name"], claim["category"])
        # Deduped AFTER resolution. A pattern that does not know which category it found
        # ("the `x` tier") carries `category: None` until here, so the same word in the
        # same field arrives twice and is one finding, not two.
        key = (claim["where"], claim["name"], where)
        if key in seen:
            continue
        seen.add(key)
        (grounded if where else ungrounded).append(dict(claim, resolved=where))
    unchecked = []
    for step in pl.get("steps") or []:
        res = ((step.get("strategy") or {}).get("resources")) or {}
        for field in ("skills", "tools"):
            for name in res.get(field) or []:
                unchecked.append({"where": f"{step.get('id')}.strategy.resources.{field}",
                                  "name": name})
    return {
        "plan": pl.get("id"),
        "title": pl.get("title"),
        "steps": len(pl.get("steps") or []),
        "grounded": grounded,
        "ungrounded": ungrounded,
        "unchecked": unchecked,
        "unchecked_note": ("skills and tools are not in the catalogue by design — they come "
                           "from the session, not from sb — so they are listed, not checked"),
        "coverage": ("structured slots exactly; prose only where the repo's own idiom puts "
                     "a catalogue name. A name invented in free prose elsewhere is not "
                     "caught here and is the judge's to spot."),
        "ok": not ungrounded,
    }


def check_report(r: dict) -> str:
    L = [f"grounding — plan {r['plan']}, {r['steps']} steps", ""]
    if r["ungrounded"]:
        L.append(f"NOT IN THE CATALOGUE ({len(r['ungrounded'])}):")
        for c in r["ungrounded"]:
            L.append(f"  {c['name']}  ({c['category'] or 'any category'}, {c['kind']}) "
                     f"— {c['where']}")
    else:
        L.append("Nothing named that the catalogue does not have.")
    L += ["", f"grounded names ({len(r['grounded'])}):"]
    for c in sorted(r["grounded"], key=lambda c: (c["resolved"], c["name"])):
        L.append(f"  {c['name']}  ({c['resolved']}) — {c['where']}")
    if r["unchecked"]:
        L += ["", f"listed, not checked ({len(r['unchecked'])}) — {r['unchecked_note']}:"]
        for c in r["unchecked"]:
            L.append(f"  {c['name']} — {c['where']}")
    L += ["", f"coverage: {r['coverage']}"]
    return "\n".join(L)


# -- the context manifest ------------------------------------------------------


def manifest(agent: str, sb: str = "sb", *, brief: Optional[str] = None,
             tier: Optional[str] = None, skills: Optional[str] = None) -> dict:
    """What one agent was given, hashed where it can be and marked where it cannot."""
    cat_text = _run(sb, "catalog")
    cat = _payload(cat_text)
    row = _payload(_run(sb, "inspect", agent=agent))
    out: dict[str, Any] = {
        "agent": {
            "name": row.get("name"), "role": row.get("role"),
            "parent": row.get("parent"), "workspace": row.get("workspace"),
            "cwd": row.get("cwd"),
            "capabilities_held": sorted(row.get("caps_held") or []),
            "capabilities_delegable": sorted(row.get("caps_delegable") or []),
            "capabilities_from_role": sorted(row.get("caps_template") or []),
            "tier_requested_at_spawn": tier,
            "tier_note": ("the tier is the operator's own `--model` at spawn; no read-only "
                          "sb command reports an agent's tier back"),
            "task": row.get("task"),
        },
        "instruction": {
            "planner": _digest(_run(sb, "planner")),
            "guide": _digest(_run(sb, "guide")),
        },
        "catalogue": dict(_digest(cat_text),
                          **{k: sorted(v) for k, v in names(cat).items()}),
        "models": _payload(_run(sb, "models")),
        "brief": None,
        "skills_and_tools": {"source": "session self-report", "reported": skills,
                             "note": SELF_REPORT},
    }
    if brief:
        text = _read_file(brief)
        out["brief"] = dict(_digest(text), path=brief)
    return out


def manifest_report(m: dict) -> str:
    a, i, c = m["agent"], m["instruction"], m["catalogue"]
    L = [f"context manifest — {a['name']} ({a['role']})", ""]
    L += [f"  workspace   {a['workspace']}",
          f"  checkout    {a['cwd']}",
          f"  parent      {a['parent']}",
          f"  held        {', '.join(a['capabilities_held']) or '(none)'}",
          f"  delegable   {', '.join(a['capabilities_delegable']) or '(none)'}",
          f"  from role   {', '.join(a['capabilities_from_role']) or '(none)'}",
          f"  tier        {a['tier_requested_at_spawn'] or '(not recorded)'} — "
          f"{a['tier_note']}", ""]
    L += [f"  planner instruction  {i['planner']['sha256'][:16]}  "
          f"{i['planner']['lines']} lines",
          f"  guide                {i['guide']['sha256'][:16]}  {i['guide']['lines']} lines",
          f"  catalogue            {c['sha256'][:16]}  {c['chars']} chars of json"]
    if m["brief"]:
        L.append(f"  brief                {m['brief']['sha256'][:16]}  {m['brief']['path']}")
    else:
        L.append("  brief                (not given to this run)")
    L += ["", "  catalogue names:"]
    for cat in ("roles", "models", "presets", "plugins", "capabilities", "library",
                "templates"):
        L.append(f"    {cat:<14}{', '.join(c[cat])}")
    st = m["skills_and_tools"]
    L += ["", f"  skills and tools: {st['reported'] or '(not reported)'}",
          f"    {st['note']}"]
    return "\n".join(L)


# -- cli -----------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    # `--sb` and `--json` are on a shared parent so they read the same either side of the
    # subcommand. Typing them after it is what everybody does, and argparse puts a
    # top-level flag before it only.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--sb", default="sb",
                        help="the sb to run. INSIDE A CLONE THIS IS `./bin/sb`: a clone's "
                             "sb run from outside it writes to the live store")
    common.add_argument("--json", action="store_true")
    p = argparse.ArgumentParser(
        parents=[common],
        description="the mechanical half of the planner evaluation pass — development only")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("manifest", parents=[common], help="what one agent was given")
    m.add_argument("agent")
    m.add_argument("--brief", help="path to the brief that was handed over")
    m.add_argument("--tier", help="the --model the agent was spawned with")
    m.add_argument("--skills", help="the agent's own report of its skills and tools")

    c = sub.add_parser("check", parents=[common], help="catalogue names a plan uses that do not exist")
    c.add_argument("plan")
    c.add_argument("--plan-json", help="captured `show <plan> --json` instead of a live store")
    c.add_argument("--catalog-json", help="captured `catalog --json` instead of a live store")

    a = p.parse_args(argv)
    if a.cmd == "manifest":
        r = manifest(a.agent, a.sb, brief=a.brief, tier=a.tier, skills=a.skills)
        print(json.dumps(r, indent=2) if a.json else manifest_report(r))
        return 0
    r = check(plan(a.plan, a.sb, source=a.plan_json),
              catalogue(a.sb, source=a.catalog_json))
    print(json.dumps(r, indent=2) if a.json else check_report(r))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
