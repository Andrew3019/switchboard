"""E3 — `sb configure`: an agent tunes itself, inside a ceiling it cannot move (spec §2.4).

Four things this unit is, and they are the four assertions worth having:

* **it applies** — a setting inside the ceiling actually changes what the delivery pass
  says, through the same `guidance.deliver` both channels already go through;
* **the ceiling holds** — a value past it is refused, and the ceiling is the ROLE
  TEMPLATE'S, so re-homing an agent under a more permissive parent does not move it;
* **safety is not tunable** — a safety-category rule is refused as a target and delivered
  anyway if a row for it reaches the table by some other route;
* **it tunes config, never rights** — a capability string is not a setting name, so there
  is no `sb configure` that widens what an agent may do.

What no test here pins is that a quieter agent is a better agent. That is a judgement
about nag-fatigue (§5) and it is settled by the `deliveries` counter over a real fleet,
not by an assertion.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import cli, guidance, roles as roles_mod, store  # noqa: E402
from switchboard.broker import Broker  # noqa: E402

from test_workspace import FakeHerdr  # noqa: E402


def rule(**kw) -> guidance.Rule:
    """One rule, straight from its authored form — the same path the TOML takes."""
    return guidance._rule(kw, kw.pop("_order", 0))


class Fixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.db = store.connect(path=self.repo / "state.db")
        self.b = Broker(self.db, FakeHerdr(self.repo / "worktrees"), repo=self.repo)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.db.close)

    def agent(self, name, role="worker", **kw):
        store.create_agent(self.db, name=name, role=role, **kw)
        return name

    def deliver(self, name, rules, command=None):
        return guidance.deliver(self.db, name, rules=rules, command=command,
                                repo=self.repo)


# ---------------------------------------------------------------------------
# It applies
# ---------------------------------------------------------------------------


class AppliesTest(Fixture, unittest.TestCase):
    def test_an_in_ceiling_setting_changes_what_is_actually_delivered(self):
        """Obj. 1, and the assertion is on DELIVERY rather than on the stored row: a
        preference that is written and never read is not a tuning, and the only proof that
        `sb configure` is wired to anything is the same `guidance.deliver` both channels
        go through saying something different afterwards."""
        self.agent("w1")
        rules = [rule(id="wide", text="a global note"),
                 rule(id="close", text="about you", role="worker",
                      when=[{"fact": "children", "op": ">=", "value": 0}])]

        said = self.deliver("w1", rules)
        self.assertIn("a global note", said)
        self.assertIn("about you", said)

        self.b.configure("reminders", "brief", me="w1")

        # `brief` keeps the rule that turns on this agent's own live state and drops the
        # standing global one — which is the whole difference between the two levels.
        rules = [rule(id="wide2", text="a global note"),
                 rule(id="close2", text="about you", role="worker",
                      when=[{"fact": "children", "op": ">=", "value": 0}])]
        said = self.deliver("w1", rules)
        self.assertNotIn("a global note", said)
        self.assertIn("about you", said)

    def test_debounce_spaces_a_repeating_rule_out_and_never_silences_it(self):
        """The second knob, and the property that makes it safe to have: it moves WHEN a
        rule is said, never whether. The repeat policy still decides that."""
        self.agent("w1")
        r = rule(id="e", text="remember", repeat="every-time",
                 when=[{"fact": "children", "op": ">=", "value": 0}])

        self.b.configure("debounce", "300", me="w1")
        self.assertIn("remember", self.deliver("w1", [r]))
        self.assertEqual(self.deliver("w1", [r]), "")           # too soon

        # The cursor is what the gap is measured from, so backdating it is the same as
        # waiting — and it is the only way to test a clock without sleeping on one.
        self.db.execute("UPDATE guidance SET delivered_at=delivered_at-400 "
                        "WHERE agent='w1'")
        self.db.commit()
        self.assertIn("remember", self.deliver("w1", [r]))

    def test_a_rule_held_back_by_a_setting_does_not_write_its_cursor(self):
        """The bug this could most easily have shipped, and E1 has the same test for the
        same reason: a rule that was not said must not be marked as said, or a
        `once`-shaped rule turned down for a while comes back already spent."""
        self.agent("w1")
        r = rule(id="o", text="global once", repeat="once")
        self.b.configure("reminders", "brief", me="w1")

        self.assertEqual(self.deliver("w1", [r]), "")
        self.assertEqual(store.guidance_cursors(self.db, "w1"), {})

        self.b.configure("reminders", "full", me="w1")
        self.assertIn("global once", self.deliver("w1", [r]))

    def test_the_readout_says_what_you_are_tuned_to_and_how_far_you_may_go(self):
        """A verb whose refusal names a ceiling has to have a way to ask what the ceiling
        is, or the only route to it is trial and error against an error message."""
        self.agent("w1")
        r = self.b.configure(me="w1")
        self.assertEqual(r["config"]["reminders"], "full")
        self.assertEqual(r["ceiling"]["debounce"], 300)


# ---------------------------------------------------------------------------
# The ceiling, and whose it is
# ---------------------------------------------------------------------------


class CeilingTest(Fixture, unittest.TestCase):
    def test_a_value_past_the_ceiling_is_refused(self):
        """Obj. 2's first half. The refusal names the role, because that is the thing the
        ceiling is pinned to and the only fact that makes it actionable."""
        self.agent("w1")
        with self.assertRaises(ValueError) as cm:
            self.b.configure("debounce", "900", me="w1")
        self.assertIn("worker", str(cm.exception))
        self.assertIn("300", str(cm.exception))
        self.assertEqual(store.config_values(self.db, "w1"), {})

        with self.assertRaises(ValueError):
            self.b.configure("reminders", "off", me="w1")

    def test_the_ceiling_is_the_role_templates_and_a_re_home_does_not_move_it(self):
        """Obj. 2, the half the design is actually about. `parent` is mutable — a promote
        re-homes an agent under somebody else — so a parent-derived ceiling would mean an
        agent's config bound changed silently, from above, with nobody having asked. The
        role is stamped at spawn and never rewritten (§6.10), so the ceiling read off it
        cannot move either.

        Written against `agents.parent` directly because the promote verb is F2's and this
        property has to hold whatever eventually rewrites that column.
        """
        self.agent("lead-x", role="lead")
        self.agent("plain", role="worker")
        self.agent("w1", role="worker", parent="plain")

        # A lead may go to 900; the worker below it may not, and that is true before and
        # after it is re-homed under the lead that can.
        self.assertEqual(self.b.configure("debounce", "900", me="lead-x")["value"], 900)
        with self.assertRaises(ValueError):
            self.b.configure("debounce", "900", me="w1")

        self.db.execute("UPDATE agents SET parent='lead-x' WHERE name='w1'")
        self.db.commit()
        self.assertEqual(store.get_agent(self.db, "w1")["parent"], "lead-x")

        with self.assertRaises(ValueError):
            self.b.configure("debounce", "900", me="w1")
        self.assertEqual(
            roles_mod.template_ceiling(self.b.roles, "worker", self.repo)["debounce"], 300)

    def test_a_stored_value_the_template_no_longer_allows_is_clamped_on_the_read(self):
        """What makes the ceiling a ceiling rather than a check somebody once passed. A
        role narrowed after an agent tuned itself would otherwise leave that agent running
        past the new bound for the rest of its life."""
        self.agent("l1", role="lead")
        self.b.configure("debounce", "900", me="l1")
        cfg = roles_mod.effective_config({"debounce": "900"}, {"debounce": 300}, self.repo)
        self.assertEqual(cfg["debounce"], 300)


# ---------------------------------------------------------------------------
# What is not tunable at all
# ---------------------------------------------------------------------------


class SafetyTest(Fixture, unittest.TestCase):
    def test_a_safety_category_cannot_be_silenced_or_quietened(self):
        """Obj. 3, at the refusal. The message says the category is not a thing to tune
        rather than accepting the value and ignoring it — a knob that silently does
        nothing is worse than no knob, because an agent then believes it is quiet."""
        self.agent("w1")
        with self.assertRaises(ValueError) as cm:
            self.b.configure(f"reminders.{guidance.SAFETY}", "off", me="w1")
        self.assertIn("safety-critical", str(cm.exception))
        self.assertEqual(store.config_values(self.db, "w1"), {})

        # An ordinary category is tunable, which is what makes the refusal above a
        # carve-out rather than the general rule.
        self.assertEqual(
            self.b.configure("reminders.advice", "brief", me="w1")["value"], "brief")

    def test_a_safety_rule_is_delivered_whatever_the_agent_has_configured(self):
        """Obj. 3, at the delivery site — the half that holds even for a row that reached
        the config table some other way. `reminders off` is beyond a worker's ceiling, so
        this writes the row the refusal would have stopped and proves the answer is the
        same: no verbosity reaches a safety rule and no debounce spaces it out."""
        self.agent("w1")
        store.set_config(self.db, "w1", "reminders", "off")
        store.set_config(self.db, "w1", "debounce", "9000")

        safe = rule(id="s", text="do not do that", category=guidance.SAFETY,
                    repeat="every-time")
        advice = rule(id="a", text="you might prefer", repeat="every-time")

        said = self.deliver("w1", [safe, advice])
        self.assertIn("do not do that", said)
        self.assertNotIn("you might prefer", said)
        self.assertIn("do not do that", self.deliver("w1", [safe]))   # nor debounced


# ---------------------------------------------------------------------------
# Config, never rights
# ---------------------------------------------------------------------------


class NotARightTest(Fixture, unittest.TestCase):
    def test_configure_cannot_name_a_capability_and_cannot_widen_a_held_set(self):
        """Obj. 5, and C2 obj. 16 from this unit's side. The two vocabularies are
        disjoint, so a capability string simply is not a setting name — the refusal comes
        from the same closed table a typo hits, with no special case that has to remember
        to enumerate the capabilities."""
        self.agent("w1")
        store.seed_capabilities(self.db, "w1", ["write-tracked"])

        for name in sorted(roles_mod.CAPABILITIES):
            with self.assertRaises(ValueError) as cm:
                self.b.configure(name, "true", me="w1")
            self.assertIn("no such setting", str(cm.exception))
        self.assertEqual(store.held_capabilities(self.db, "w1"), {"write-tracked"})

    def test_it_is_self_directed_and_the_human_is_not_an_agent(self):
        """There is no target parameter anywhere on this path, which is why one agent
        cannot configure another: not a flag, not a broker argument, not a store column."""
        with self.assertRaises(ValueError) as cm:
            self.b.configure("reminders", "brief", me="human")
        self.assertIn("agent that runs it", str(cm.exception))
        with self.assertRaises(TypeError):
            self.b.configure("reminders", "brief", "w1", me="w1")   # no third positional


# ---------------------------------------------------------------------------
# The verb itself
# ---------------------------------------------------------------------------


class CommandTest(unittest.TestCase):
    """Driven through `cli.main`, because what is being pinned is the WIRING: parser to
    broker to store to output, in the process an agent actually runs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir(parents=True)
        for cmd in (["git", "init", "-q", "-b", "main"],
                    ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                     "commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(cmd, cwd=self.repo, capture_output=True)
        db = store.connect(self.repo)
        store.create_agent(db, name="w1", role="worker", workspace="w1", branch="w1",
                           cwd=str(self.repo))
        store.seed_capabilities(db, "w1", ["write-tracked"])
        db.close()
        cwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(os.chdir, cwd)
        env = mock.patch.dict(os.environ, {"SB_AGENT": "w1"}, clear=False)
        env.start()
        self.addCleanup(env.stop)

    def run_sb(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_set_then_read_then_refused(self):
        code, out, _ = self.run_sb("configure", "reminders", "brief")
        self.assertEqual(code, 0)
        self.assertIn("reminders = brief", out)

        code, out, _ = self.run_sb("--json", "configure")
        self.assertEqual(json.loads(out)["config"]["reminders"], "brief")

        code, _, err = self.run_sb("configure", "debounce", "9000")
        self.assertEqual(code, 1)
        self.assertIn("may not set", err)

    def test_the_readout_names_what_this_agent_has_tuned(self):
        """E2's footer grew the one line it said it was leaving to this unit — the config
        actually in effect, now that there is per-agent config to show."""
        self.run_sb("configure", "debounce", "60")
        _, out, _ = self.run_sb("grant", "nobody", "fork")
        self.assertIn("you have tuned: debounce 60", out)


if __name__ == "__main__":
    unittest.main()
