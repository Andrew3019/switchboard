"""#326 — roles are soft guidance, not permission classes.

Three decisions, one test each, and each one is a thing that was TRUE BEFORE and must not
come back:

* the shipped role set is the v2 set — `worker` the general-purpose default, `researcher`,
  `reviewer`, `planner`, `dispatcher` — with `lead`, `builder`, `qa` and `py-qa` gone;
* no role restricts what an agent may do: every role resolves to the whole vocabulary, and
  the role that used to be read-only is refused nothing;
* nothing running is orphaned: a row seeded under the old narrow templates, under a role
  string this repo has since retired, still resolves and is still refused nothing.

Spec §5: "A role describes the job the agent was launched to do; it is not a permission
class... They do not impose hard capability restrictions: a researcher can still edit code,
run commands, delegate and spawn."
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import roles as roles_mod  # noqa: E402
from switchboard import store  # noqa: E402
from switchboard.broker import (  # noqa: E402
    CAP_DISPATCH, CAP_FORK, CAP_SPAWN, CAP_WRITE_TRACKED,
)

from test_grants import Fixture  # noqa: E402

RETIRED = ("lead", "builder", "qa", "py-qa")


class ShippedRoleSetTest(Fixture, unittest.TestCase):

    def test_the_shipped_set_is_the_v2_set_and_worker_is_the_default(self):
        """The vocabulary itself, and the two settings that decide what a spawn with no
        `--role` gets and what an unknown stored role reads as. `planner` is in the set and
        comes from the plans plugin, which ships enabled."""
        self.assertEqual(sorted(self.b.roles),
                         ["dispatcher", "planner", "researcher", "reviewer", "worker"])
        for setting in ("default_role", "fallback_role"):
            with self.subTest(setting=setting):
                self.assertEqual(
                    roles_mod.config.setting(f"vocabulary.{setting}", repo=self.repo),
                    "worker")

    def test_every_retired_name_still_resolves_and_spawns_a_worker(self):
        """The migration, for every repo that does not keep the old roles as its own: one
        alias each, resolving ALL the way, so the row, the prompt and the board agree.

        A repo that DOES keep them — this one does, under `.switchboard/roles/` — keeps
        them instead: `roles.get` reads the role table before the alias table."""
        top = self.top()
        for retired in RETIRED:
            with self.subTest(role=retired):
                self.assertNotIn(retired, self.b.roles)
                kid = self.b.delegate("t", topic=retired, role=retired, me=top)
                self.assertEqual(store.get_agent(self.db, kid)["role"], "worker")


class NoRoleIsAPermissionClassTest(Fixture, unittest.TestCase):

    def test_no_role_is_refused_anything_and_that_includes_the_read_only_one(self):
        """The whole contract, at the gate rather than at the template: every role seeds
        the whole vocabulary, and a `researcher` — the role that held `spawn` alone — may
        write tracked files, dispatch and fork with nothing refusing it.

        `write-tracked` is still CHECKED, at `sb merge` and flagged at `sb done`
        (`roles.side_effect_capabilities`): what changed is that the answer no longer
        depends on which role the agent was spawned under."""
        top = self.top()
        for role in self.b.roles:
            with self.subTest(role=role):
                self.assertEqual(set(self.b.seed_for(role, is_top=False)),
                                 set(roles_mod.CAPABILITIES))
        r = self.spawn(top, "researcher", "r")
        for cap in (CAP_SPAWN, CAP_DISPATCH, CAP_FORK, CAP_WRITE_TRACKED):
            with self.subTest(cap=cap):
                self.b.require_capability(r, cap)          # no ValueError, for any of them
        self.assertTrue(self.b.delegate("t", topic="w", role="worker", me=r))

    def test_the_two_refusals_that_are_not_role_classes_are_untouched(self):
        """What #326 deliberately did NOT neutralize, because neither is a fact about a
        role: the top's fixed set (§2.0 — a PLACEMENT, and the reason it holds no
        `write-tracked` is that it works over a person's own checkout), and the vocabulary
        being closed at the grant path."""
        self.assertEqual(self.b.seed_for("dispatcher", is_top=True),
                         sorted(roles_mod.TOP_CAPABILITIES))
        self.assertNotIn(CAP_WRITE_TRACKED, self.b.seed_for("dispatcher", is_top=True))
        top = self.top()
        w = self.spawn(top, "worker", "w")
        with self.assertRaises(ValueError):
            self.b.grant(w, "wrte-tracked", me=top)
        with self.assertRaises(ValueError):
            self.b.grant(w, "start", me=top)


class NothingRunningIsOrphanedTest(Fixture, unittest.TestCase):

    def test_a_row_seeded_under_the_old_narrow_template_is_refused_nothing(self):
        """The migration for a fleet that is already up. These rows exist right now: a
        `qa` seeded `spawn` alone, a `py-qa` seeded `write-tracked` alone (its role file
        said `delegate = false`), under role strings the shipped vocabulary has retired.

        Their live set is read as the stored rows UNIONED with what their role resolves to
        now (`Broker._held_of`), so they keep every capability they were seeded with and
        are refused nothing — including the `spawn` a `py-qa` never had."""
        top = self.top()
        for name, seed in (("qa-live", [CAP_SPAWN]),
                           ("py-qa-live", [CAP_WRITE_TRACKED])):
            store.create_agent(self.db, name=name, role=name.rsplit("-", 1)[0],
                               parent=top, workspace="ws", branch="ws",
                               cwd=str(self.repo))
            store.seed_capabilities(self.db, name, seed)
            with self.subTest(agent=name):
                for cap in roles_mod.CAPABILITIES:
                    self.b.require_capability(name, cap)   # no ValueError, for any of them
                self.assertTrue(self.b.delegate("t", topic=name, role="worker", me=name))

    def test_a_retired_role_string_still_reads_back_off_a_stored_row(self):
        """`get_or_fallback` is the reader every stored row goes through — restore, the
        board, the model of a live agent — and it must not refuse a name the vocabulary
        has retired, or the agent becomes unrestorable."""
        table = self.b.roles
        for retired in RETIRED:
            with self.subTest(role=retired):
                got = roles_mod.get_or_fallback(table, retired, self.repo)
                self.assertTrue(got.prompt)
                self.assertEqual(got.capabilities, table["worker"].capabilities)


if __name__ == "__main__":
    unittest.main()
