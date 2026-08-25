"""The planner evaluation pass — the development-only cases, rubric and harness.

Pinning decisions, not buying confidence. Most of this pass is prose (`SKILL.md`,
`RUBRIC.md`, the five case files) and most of it is judgement, which is the point: whether a
real plan writer plans proportionally is not a thing a test can answer. What is pinned here
is the small mechanical half and the one structural property of the committed cases:

1. The harness only ever reads. Its six argvs are a constant, every one of them a read, and
   the two that take a name take ONLY a name — no caller can reach the verb words.
2. The grounding check finds an invented catalogue name and clears a plan that has none,
   and it lists skills and tools rather than failing them, because the catalogue says in as
   many words that skills and tools are not in it.
3. Every case file keeps its expected signal OUT of the half that is handed to a planner. A
   planner that can read the answer makes the evaluation self-certifying, which is the
   failure mode the whole pass is exposed to, and it is one line of a file away at any time.

NOTHING HERE CALLS A MODEL OR SPAWNS AN AGENT, and that is a requirement rather than a
style: CI runs `python -m pytest tests` unchanged, so a file dropped in this directory is in
CI automatically. The fixtures are hand-written to the plugin's own documented record and no
store is touched.

Unproven here, and worth saying rather than leaving to be discovered: that the rubric
produces consistent scores, that the runbook is followable, and that the prose patterns in
the check catch a real planner's invention rather than a fixture's. The first two are
answered by the live run and the fresh judge, not by this file. The third is a recall
question the check's own docstring concedes and the rubric hands to the judge.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "defaults" / "plugins" / "plans" / "evals"


def _load():
    """Import `harness.py` by path — it is a script beside a plugin, not a package."""
    spec = importlib.util.spec_from_file_location("plans_evals", EVALS / "harness.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plans_evals"] = mod
    spec.loader.exec_module(mod)
    return mod


h = _load()


# A catalogue in the shape `sb plugin plans catalog --json` returns, cut to the names the
# check reads. Hand-written from the plugin's documented output, not captured from a store.
CATALOG = {
    "roles": [{"name": "lead"}, {"name": "researcher"}, {"name": "worker"}],
    "models": {"tiers": [{"name": "cheap"}, {"name": "strong"}]},
    "presets": {"available": ["adversarial", "evidence"], "every_agent": ["@plans"]},
    "plugins": ["plans"],
    "capabilities": ["fork", "spawn", "write-tracked"],
    "library": [{"name": "change-approval"}, {"name": "plan-review"}],
    "templates": [{"name": "docs"}],
}


def _step(sid, **strategy):
    return {"id": sid, "def": strategy.pop("def_", None), "strategy": strategy or None}


GROUNDED = {"id": "p-1", "title": "a plan that names only what exists", "steps": [
    _step("step-1", model="strong — the judgement is the whole of this step",
          orchestration="one agent, `--role worker`, held `spawn` for its own helper",
          resources={"presets": ["evidence"], "skills": ["Bash"], "tools": ["rg"]}),
    _step("step-2", def_="plan-review", model="strong and fresh"),
]}

INVENTED = {"id": "p-2", "title": "a plan that names things this repo does not have",
            "steps": [
                # An invented library step, an invented preset and an invented role, one in
                # each kind of position the check reads: a `def`, a structured resource
                # list, and the repo's own spawn idiom in free prose.
                _step("step-1", def_="deep-review",
                      orchestration="spawn it with `--role verifier` and `--model turbo`",
                      resources={"presets": ["paranoid"]}),
            ]}


class ReadOnlyTest(unittest.TestCase):
    """The hard rule, checked where it is structural rather than where it is written down."""

    READS = {("plugin", "plans", "planner"), ("plugin", "plans", "guide"),
             ("plugin", "plans", "catalog", "--json"), ("models", "--json"),
             ("inspect", "{agent}", "--json"),
             ("plugin", "plans", "show", "{plan}", "--json")}

    def test_every_argv_is_a_read_and_the_verbs_are_constants(self):
        # The whole of "this pass never edits": there is no argv here that writes, and no
        # code path that takes a verb from an argument. If a later edit adds `tick` or
        # `note` to this table, or parameterises a verb word, this is the line that says no.
        self.assertEqual(set(h.SB_READS.values()), self.READS)
        for key in h.SB_READS:
            holes = {"agent": "some-agent", "plan": "p-9"}
            argv = h._argv(key, **holes)
            filled = [w for w in argv if w in holes.values()]
            self.assertLessEqual(len(filled), 1, f"{key} takes more than a name")
            # Everything that is not the name came from the constant, in order.
            self.assertEqual([w for w in argv if w not in holes.values()],
                             [w for w in h.SB_READS[key] if not w.startswith("{")])

    def test_a_missing_name_is_refused_rather_than_guessed(self):
        # A hole left unfilled would otherwise reach the shell as the literal `{plan}`,
        # which is a command that fails in a way nobody reads as "the caller forgot".
        with self.assertRaises(KeyError):
            h._argv("plan")


class GroundingTest(unittest.TestCase):
    """The one success criterion this unit can compute: invents no catalogue entries."""

    def test_it_names_what_the_catalogue_does_not_have(self):
        r = h.check(INVENTED, CATALOG)
        self.assertFalse(r["ok"])
        self.assertEqual({c["name"] for c in r["ungrounded"]},
                         {"deep-review", "paranoid", "verifier", "turbo"})
        # And it says WHERE, because "something in this plan is invented" is not a finding
        # anybody can act on.
        where = {c["name"]: c["where"] for c in r["ungrounded"]}
        self.assertEqual(where["deep-review"], "step-1.def")
        self.assertEqual(where["paranoid"], "step-1.strategy.resources.presets")

    def test_a_plan_that_names_only_real_things_comes_back_clean(self):
        r = h.check(GROUNDED, CATALOG)
        self.assertTrue(r["ok"], r["ungrounded"])
        found = {(c["name"], c["resolved"]) for c in r["grounded"]}
        self.assertLessEqual({("plan-review", "library"), ("evidence", "presets"),
                              ("worker", "roles"), ("spawn", "capabilities"),
                              ("strong", "models")}, found)

    def test_skills_and_tools_are_listed_and_never_failed(self):
        # The catalogue does not carry them — they come from the session an agent runs in —
        # so there is nothing to check them against. Marking them ungrounded would be the
        # harness inventing a rule the catalogue does not have.
        r = h.check(GROUNDED, CATALOG)
        self.assertEqual({c["name"] for c in r["unchecked"]}, {"Bash", "rg"})
        self.assertNotIn("Bash", {c["name"] for c in r["ungrounded"]})


class CasesTest(unittest.TestCase):
    """The split that keeps the evaluation from certifying itself."""

    BRIEF = re.compile(r"^## Brief\b.*$", re.M)
    SIGNAL = re.compile(r"^## Expected signal\b.*$", re.M)

    def test_every_case_has_a_brief_half_and_an_answer_half_in_that_order(self):
        cases = sorted((EVALS / "cases").glob("case-*.md"))
        self.assertEqual(len(cases), 5, [c.name for c in cases])
        for path in cases:
            text = path.read_text(encoding="utf-8")
            brief, signal = self.BRIEF.search(text), self.SIGNAL.search(text)
            self.assertIsNotNone(brief, f"{path.name} has no brief half")
            self.assertIsNotNone(signal, f"{path.name} has no expected-signal half")
            # Order is the whole guarantee: the runbook says hand over the brief section and
            # nothing below it, so the answer being BELOW it is what makes that instruction
            # possible to follow.
            self.assertLess(brief.start(), signal.start(), path.name)
            for heading in (brief, signal):
                self.assertIn("hand", heading.group(0).lower(), path.name)


if __name__ == "__main__":
    unittest.main()
