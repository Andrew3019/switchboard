"""The analysis pass — the recurring read of the plan records that proposes what to add.

Pinning decisions, not buying confidence. The skill is mostly prose (`SKILL.md`); what is
tested here is `evidence.py`, the mechanical half, and only the four things the behavioural
contract makes promises about that prose alone cannot keep:

1. It never edits. The one sb command it runs is a read, it is a constant, and no argument
   reaches it — so there is no way to turn this pass into a write by calling it oddly.
2. It tells rework-as-try-count from rework-as-added-step, off the changelog ACTION rather
   than off the step, and never adds the two together. A try count with no `rework` entry
   behind it is a third thing and is counted as neither.
3. It flags abandoned plans, and a proposal standing only on abandoned or unreadable plans
   comes out marked weak rather than as a finding.
4. Every output names the bias toward jobs that went well — the human report and the JSON.

Unproven here, and worth saying: that an agent reading `SKILL.md` actually judges well, and
that the report is legible to somebody who was not on the jobs. Both are workflow questions
and neither is a code one. Also unproven mechanically: that `sb plugin plans list --all
--json` keeps the shape these fixtures use — the fixtures are hand-written from the plugin's
documented record, not captured from a live store, so a format change would break the pass
before it broke this file.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "defaults" / "plugins" / "plans" / "analysis"


def _load():
    """Import `evidence.py` by path — it is a skill file beside a plugin, not a package."""
    spec = importlib.util.spec_from_file_location("plans_analysis", SKILL / "evidence.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plans_analysis"] = mod
    spec.loader.exec_module(mod)
    return mod


ev = _load()


def _plan(pid, title, condition, steps, changelog, **extra):
    return dict({"id": pid, "title": title, "condition": condition, "worktree": "here",
                 "workspace": "ws", "workspace_from": "agent", "checkout": f"/w/{pid}",
                 "steps": steps, "changelog": changelog, "notes": [],
                 "created_by": "lead", "created_at": 1754570000}, **extra)


def _step(sid, name, progress="done", tries=1, **extra):
    return dict({"id": sid, "name": name, "def": None, "obliged_by": None,
                 "progress": progress, "why": None, "owner": "worker", "tries": tries,
                 "notes": [], "deps": [], "checkpoints": []}, **extra)


def _entry(action, detail, reason=None, by="lead"):
    return {"at": 1754570000, "by": by, "action": action, "reason": reason,
            "detail": detail}


# A corpus of four: one that ran to a shape, one that fell apart, one where a step was
# re-entered, and one where a step was added mid-job. The last two share the shape of the
# first so that a recurrence is actually there to be found.
WELL_RUN = _plan(
    "p-1", "ship the parser", "finished",
    [_step("s-1", "write the brief"), _step("s-2", "implement it"),
     _step("s-3", "review the diff")],
    [_entry("create", "3 steps (s-1, s-2, s-3)", "shaping the job"),
     _entry("tick", "s-1 open → done", "brief written"),
     _entry("tick", "s-2 open → done", "landed"),
     _entry("tick", "s-3 open → done", "reviewed")])

ABANDONED = _plan(
    "p-2", "rewrite the sweeper", "abandoned",
    [_step("s-4", "write the brief"), _step("s-5", "implement it", progress="open"),
     _step("s-6", "review the diff", progress="open")],
    [_entry("create", "3 steps (s-4, s-5, s-6)", "shaping the job"),
     _entry("tick", "s-4 open → done", "brief written")],
    worktree="gone")

TRY_COUNT = _plan(
    "p-3", "ship the exporter", "finished",
    [_step("s-7", "write the brief"), _step("s-8", "implement it", tries=3),
     _step("s-9", "review the diff")],
    [_entry("create", "3 steps (s-7, s-8, s-9)", "shaping the job"),
     _entry("rework", "s-8 done → open, try 2", "review found the schema wrong"),
     _entry("rework", "s-8 done → open, try 3", "review found the schema wrong again"),
     _entry("tick", "s-8 open → done", "third time")])

ADDED_STEP = _plan(
    "p-4", "ship the importer", "finished",
    [_step("s-10", "write the brief"), _step("s-11", "implement it"),
     _step("s-12", "review the diff"), _step("s-13", "backfill the fixtures")],
    [_entry("create", "3 steps (s-10, s-11, s-12)", "shaping the job"),
     _entry("add-step", "s-13 backfill the fixtures", "review rejected: fixtures stale")])

# A second plan that adds the same step, so the add-step pattern recurs rather than being
# one job's accident — RECURS is two plans and a proposal off one would be noise.
ADDED_AGAIN = _plan(
    "p-5", "ship the webhook", "finished",
    [_step("s-14", "implement it"), _step("s-15", "backfill the fixtures")],
    [_entry("create", "1 step (s-14)", "shaping the job"),
     _entry("add-step", "s-15 backfill the fixtures", "same stale fixtures again")])

CORPUS = [WELL_RUN, ABANDONED, TRY_COUNT, ADDED_STEP, ADDED_AGAIN]


class ReadOnlyTest(unittest.TestCase):
    """The hard rule, checked where it is structural rather than where it is written down."""

    def test_the_only_sb_command_is_a_read_and_takes_nothing_from_the_caller(self):
        # The argv is a constant naming `list`, which mutates nothing. If a later edit ever
        # parameterises the verb, this is the line that says no.
        self.assertEqual(ev.SB_ARGV, ("plugin", "plans", "list", "--all", "--json"))
        seen = []

        def fake_run(argv, **kw):
            seen.append(argv)
            return mock.Mock(returncode=0, stdout=json.dumps({"ok": True, "data": CORPUS}),
                             stderr="")

        with mock.patch.object(ev.subprocess, "run", fake_run):
            plans = ev.records("/bin/sb")
        self.assertEqual(seen, [["/bin/sb", *ev.SB_ARGV]])
        self.assertEqual([p["id"] for p in plans], [p["id"] for p in CORPUS])

    def test_the_file_has_no_way_to_write_anything(self):
        # Cheap and blunt on purpose. The pass proposes, and the way it would stop
        # proposing is somebody adding one of these to it — which a grep catches in review
        # where reading the whole file again does not. There is exactly one subprocess
        # call, so "the only command is a read" is a claim about the whole file and not
        # only about the path the test above happened to take.
        src = (SKILL / "evidence.py").read_text(encoding="utf-8")
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        code = "\n".join(ln for ln in code.splitlines() if not ln.lstrip().startswith("#"))
        self.assertEqual(code.count("subprocess."), 1)
        self.assertIn("subprocess.run([sb, *SB_ARGV]", code)
        for writer in ("write_text", "os.replace", "shutil.", "os.remove", "unlink",
                       "json.dump(", "mkdir"):
            self.assertNotIn(writer, code, f"{writer} must not be reachable from this pass")
        self.assertNotRegex(code, r"open\([^)]*['\"][wax]")


class ReworkTest(unittest.TestCase):
    """The two kinds, from the changelog action, never merged."""

    def setUp(self):
        self.s = ev.survey(CORPUS)

    def test_try_count_and_added_step_are_counted_apart(self):
        r = self.s["rework"]
        self.assertEqual(r["counts"]["try_count_entries"], 2)      # both on s-8
        self.assertEqual(r["counts"]["added_step_entries"], 2)     # s-13 and s-15
        self.assertEqual(r["counts"]["steps_reworked"], 1)
        self.assertEqual({t["step"] for t in r["by_try_count"]}, {"s-8"})
        self.assertEqual({a["step"] for a in r["by_added_step"]}, {"s-13", "s-15"})
        # The reason the lead supplied is what says which kind an add-step was, so it is
        # carried through rather than summarised away.
        self.assertIn("review rejected", " ".join(
            a["reason"] for a in r["by_added_step"]))

    def test_a_try_count_with_no_rework_entry_is_neither_kind(self):
        # A hand-edited record: tries went up without a verb. Counting it as rework would
        # invent a signal; counting it as an added step would invent the wrong one.
        hand = _plan("p-9", "hand-edited", "finished",
                     [_step("s-90", "implement it", tries=4)],
                     [_entry("create", "1 step (s-90)", "shaping")])
        s = ev.survey([hand])
        self.assertEqual(s["rework"]["counts"]["try_count_entries"], 0)
        self.assertEqual(s["rework"]["counts"]["added_step_entries"], 0)
        self.assertEqual([u["step"] for u in s["rework"]["unexplained_tries"]], ["s-90"])
        self.assertIn("edited outside the verbs", " ".join(s["gaps"]))

    def test_the_two_kinds_propose_different_things(self):
        kinds = {p["kind"]: p for p in self.s["proposals"]}
        # A step re-entered in place: the shape was right, so what is proposed is about how
        # the step is run.
        self.assertIn("optimisation or preset", kinds)
        self.assertIn("s-8", json.dumps(self.s["rework"]["by_try_count"]))
        # A step added mid-job, twice: the shape was wrong, so what is proposed is a step
        # or a template.
        self.assertIn("step or template", kinds)
        self.assertIn("backfill the fixtures", kinds["step or template"]["propose"])


class AbandonedTest(unittest.TestCase):
    """Derailed jobs are flagged, and never quietly become evidence that something worked."""

    def test_abandoned_is_flagged_with_what_was_left_open(self):
        c = ev.survey(CORPUS)["corpus"]
        self.assertEqual([f["plan"] for f in c["abandoned"]], ["p-2"])
        self.assertEqual(len(c["abandoned"][0]["open"]), 2)
        self.assertNotIn("p-2", c["complete"])
        self.assertIn("ABANDONED", ev.report(ev.survey(CORPUS)))

    def test_a_proposal_standing_only_on_derailed_plans_is_weak(self):
        # Two abandoned plans that share a freehand step: the pattern is real and the
        # evidence is not. It is kept — what derailed is worth reading — and marked.
        gone = [_plan(f"p-2{i}", "fell apart", "abandoned",
                      [_step(f"s-2{i}0", "chase the flake", progress="open"),
                       _step(f"s-2{i}1", "chase the flake twice", progress="open")],
                      [_entry("create", "2 steps", "shaping")], worktree="gone")
                for i in (1, 2)]
        s = ev.survey(gone)
        self.assertTrue(s["proposals"], "the pattern should still be reported")
        for p in s["proposals"]:
            self.assertEqual(p["strength"], "weak")
            self.assertIn("never as what worked", " ".join(p["caveats"]))

    def test_a_plan_with_no_condition_is_unreadable_rather_than_assumed_fine(self):
        bare = dict(WELL_RUN)
        bare.pop("condition")
        c = ev.survey([bare])["corpus"]
        self.assertEqual([f["plan"] for f in c["unreadable"]], ["p-1"])
        self.assertEqual(c["complete"], [])


class BiasTest(unittest.TestCase):
    """Named in every output, because a reader who forgets it reads the survey wrong."""

    def test_the_report_opens_and_closes_with_it(self):
        text = ev.report(ev.survey(CORPUS))
        self.assertTrue(text.startswith("BIAS —"))
        self.assertTrue(text.rstrip().endswith(ev.BIAS))
        self.assertIn("biased toward jobs that went well", ev.BIAS)

    def test_it_is_in_the_json_and_on_every_proposal(self):
        s = ev.survey(CORPUS)
        self.assertEqual(s["bias"], ev.BIAS)
        self.assertTrue(s["proposals"])
        for p in s["proposals"]:
            self.assertIn(ev.BIAS, p["caveats"])

    def test_an_empty_corpus_still_says_it(self):
        # The one output most likely to be read as "nothing to see here" is exactly the one
        # that needs the caveat: an empty corpus is not evidence that nothing recurs.
        s = ev.survey([])
        self.assertEqual(s["bias"], ev.BIAS)
        self.assertIn(ev.BIAS, ev.report(s))
        self.assertEqual(s["proposals"], [])


class ProposalTest(unittest.TestCase):
    """That the pass proposes something sensible, and says nothing when nothing recurs."""

    def test_a_step_written_by_hand_in_several_plans_is_proposed_for_the_library(self):
        s = ev.survey(CORPUS)
        promote = [p for p in s["proposals"] if p["kind"] == "library step"]
        names = {p["propose"] for p in promote}
        self.assertTrue(any("review the diff" in n for n in names), names)
        one = next(p for p in promote if "review the diff" in p["propose"])
        # Evidence is plan ids with their conditions, so the claim can be read back — and
        # the abandoned plan sharing the step drops it to `mixed` rather than `supported`.
        self.assertIn("p-1", one["evidence"]["plans"])
        self.assertEqual(one["strength"], "mixed")
        self.assertEqual(one["evidence"]["conditions"]["p-2"], "abandoned")

    def test_one_plan_is_not_a_pattern(self):
        self.assertEqual(ev.survey([WELL_RUN])["proposals"], [])

    def test_a_named_step_usually_skipped_is_raised_against_the_catalogue(self):
        # Named steps, as `list --json` hands them back: `def` is the link and `name` is the
        # library's words resolved in on the way out.
        def named(sid, key, words, **extra):
            return dict(_step(sid, words, **extra), **{"def": key})

        skipped = [_plan(f"p-3{i}", "ship it", "finished",
                         [named(f"s-3{i}0", "merge", "merge"),
                          named(f"s-3{i}1", "merge-review", "merge review",
                                progress="skipped", why="one review covered both",
                                obliged_by=f"s-3{i}0")],
                         [_entry("name-step", f"s-3{i}0 merge", "landing")])
                   for i in (1, 2)]
        s = ev.survey(skipped)
        review = [p for p in s["proposals"] if p["kind"] == "catalogue review"]
        self.assertTrue(review, s["proposals"])
        self.assertIn("merge-review", review[0]["propose"])
        self.assertIn("one review covered both", " ".join(review[0]["caveats"]))


class GapTest(unittest.TestCase):
    """What the record could not answer is said out loud, and no field is invented to fix it."""

    def test_missing_reasons_are_reported_rather_than_guessed(self):
        mute = _plan("p-8", "quiet", "finished",
                     [_step("s-80", "implement it", tries=2)],
                     [_entry("create", "1 step (s-80)", "shaping"),
                      _entry("rework", "s-80 done → open, try 2", None),
                      _entry("add-step", "s-81 fix it up", None)])
        gaps = " ".join(ev.survey([mute])["gaps"])
        self.assertIn("rework entr", gaps)
        self.assertIn("add-step entr", gaps)
        self.assertIn("no notes at all", gaps)


if __name__ == "__main__":
    unittest.main()
