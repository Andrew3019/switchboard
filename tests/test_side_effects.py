"""E4 — `write-tracked` as ONE INSTANCE of a reusable side-effect capability class (§2.1).

The claim under test is not about `write-tracked` at all. It is that the class is a class:
a repo declares its own side-effect capability in its own settings file — `deploy`, here —
and gets the same vocabulary, the same grants and the same refusal at the same chokepoint,
with **no structural change** and **no second enforcement path**. If adding the second
capability took code, the first was never an instance of anything.

REAL GIT and a REAL repo settings file, for the same reason `test_merge` uses real git: the
enforcement point is `sb merge`, whose refusal is only meaningful against a branch that
actually exists, and the declaration is a TOML layer whose merge rules are the thing being
relied on. Each test builds its own tmp repo, so this is xdist-safe.

What is proven here, and what is not:

  - **proven**: a repo-declared cap refuses at the merge boundary by the same call that
    refuses `write-tracked`; granting it lets the same merge through; `write-tracked` still
    refuses exactly as D3 left it; the declared string is grantable (a gate with no key is
    no gate); it is NOT a per-write gate — the refused child wrote, committed and pushed
    nothing was stopped, and only the boundary said no; `done` FLAGS and never refuses, only
    for an isolated agent with tracked work behind it.
  - **not proven, and not provable here**: that the check binds an agent that ignores the
    sanctioned path. It does not — sb has no filesystem chokepoint (`hooks.py` installs
    `UserPromptSubmit` and `Stop`, there is no `PreToolUse`), so an agent with its own
    `git`/`gh` pushes and opens a PR by hand and nothing here sees it. That is stated, in
    the code and in the settings file, rather than tested: it is the accepted limit of the
    whole class, not a gap in it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import roles as roles_mod  # noqa: E402
from switchboard import store  # noqa: E402
from switchboard.broker import BOUNDARY_DONE, BOUNDARY_MERGE, Broker  # noqa: E402

from test_merge import Fixture  # noqa: E402


class DeclaringFixture(Fixture):
    """`test_merge`'s repo, plus this repo's own `[capabilities.side_effects]` table."""

    def declare(self, body: str) -> None:
        """Write this repo's settings layer and re-read the config through a fresh broker."""
        d = self.repo / ".switchboard"
        d.mkdir(exist_ok=True)
        (d / "settings.toml").write_text(body)
        self.b = Broker(self.db, self.h, repo=self.repo)


class RepoMintedCapabilityTest(DeclaringFixture, unittest.TestCase):
    """Objective 2: a second capability, on the same substrate, with no structural change."""

    def test_a_repo_declared_cap_refuses_at_the_same_merge_boundary(self):
        self.declare('[capabilities.side_effects]\ndeploy = ["merge"]\n')
        lead = self._lead()
        self._child("worker-one", file="one.txt", text="one\n")
        # It holds `write-tracked` — the shipped instance is satisfied — and the merge is
        # still refused, by the cap this repo minted for itself.
        self.assertTrue(self.b.holds_capability("worker-one", "write-tracked"))
        with self.assertRaises(ValueError) as cm:
            self.b.merge("worker-one", me=lead)
        self.assertIn("deploy", str(cm.exception))
        self.assertNotIn("one.txt", self.files(self.lead_path))

    def test_granting_the_declared_cap_lets_the_same_merge_through(self):
        """The key to the gate is `sb grant`, unchanged — subtree-scoped, fail-closed, and
        knowing nothing about which string this is."""
        self.declare('[capabilities.side_effects]\ndeploy = ["merge"]\n')
        lead = self._lead()
        self._child("worker-one", file="one.txt", text="one\n")
        # Both rows seeded from their templates, so the grant below is read off the
        # capability table rather than derived — the shape a real spawn leaves.
        store.seed_capabilities(self.db, "worker-one", ["write-tracked"])
        # The lead holds the minted cap — a deploy repo would name it in its own lead
        # template, which is the same seed — and passes it down the ordinary way, through
        # the ordinary subtree-scoped grant.
        store.seed_capabilities(self.db, lead,
                                ["spawn", "dispatch", "fork", "write-tracked", "deploy"])
        self.b.grant("worker-one", "deploy", me=lead)
        self.assertEqual(self.b.merge("worker-one", me=lead)["status"], "merged")
        self.assertIn("one.txt", self.files(self.lead_path))

    def test_a_declared_cap_is_part_of_the_vocabulary_grant_accepts(self):
        """A gate you cannot grant past is a gate with no key: declaring the string has to
        be the same act as minting it."""
        self.declare('[capabilities.side_effects]\ndeploy = ["merge"]\n')
        self.assertIn("deploy", self.b.known_capabilities())
        self.assertIn("write-tracked", self.b.known_capabilities())
        self.assertNotIn("start", self.b.known_capabilities())

    def test_start_can_never_be_declared_a_side_effect_capability(self):
        """The one string that must not become grantable, dropped whatever a file says —
        this path feeds the grant vocabulary, so it is a path that could reopen it."""
        self.declare('[capabilities.side_effects]\nstart = ["merge"]\n')
        self.assertNotIn("start", self.b.known_capabilities())
        self.assertNotIn("start", self.b.side_effect_capabilities(BOUNDARY_MERGE))

    def test_the_shipped_instance_still_refuses_exactly_as_d3_left_it(self):
        """No regression: `write-tracked` is checked on the CHILD at the merge boundary,
        and the message still names it."""
        lead = self._lead()
        self._child("researcher-notes", file="notes.md", text="read only\n",
                    role="researcher")
        with self.assertRaises(ValueError) as cm:
            self.b.merge("researcher-notes", me=lead)
        self.assertIn("write-tracked", str(cm.exception))
        self.assertNotIn("notes.md", self.files(self.lead_path))


class NotAPerWriteGateTest(DeclaringFixture, unittest.TestCase):
    """Objectives 4-5: this is post-hoc on the sanctioned path, not a preventive gate — and
    it is meant to be. Asserted, because "not a security control" is a claim about behaviour
    and an implementation that quietly grew a per-write refusal would still pass every test
    above."""

    def test_the_agent_writes_and_commits_freely_and_only_the_boundary_refuses(self):
        self.declare('[capabilities.side_effects]\ndeploy = ["merge"]\n')
        lead = self._lead()
        # A whole worktree of work, committed, by an agent holding neither cap this repo
        # checks. Nothing refused any of it, because nothing in sb was ever asked.
        self._child("researcher-notes", file="notes.md", text="read only\n",
                    role="researcher")
        child_path = self.root / "wt" / "researcher-notes"
        self.assertIn("notes.md", self.files(child_path))
        self.assertNotEqual(self.rev("researcher-notes"), self.base)
        # The refusal exists at exactly one place: the boundary.
        with self.assertRaises(ValueError):
            self.b.merge("researcher-notes", me=lead)

    def test_the_gate_is_one_call_at_one_chokepoint_not_a_second_refusal_path(self):
        """Objective 1's structural half: generalizing the class added a LOOP, not another
        enforcement path. Everything the class refuses goes through `require_capability`."""
        import inspect
        # Everything after the docstring, with comments dropped: what the verb DOES.
        body = "\n".join(ln for ln in inspect.getsource(Broker.merge).split('"""')[-1]
                         .splitlines() if not ln.lstrip().startswith("#"))
        self.assertEqual(body.count("require_capability"), 1)
        # And the strings it requires are read, never named: no capability literal in the
        # verb at all.
        self.assertNotIn("write-tracked", body)


class DoneBoundaryTest(DeclaringFixture, unittest.TestCase):
    """Objective 1's second boundary, and objective 7's honest reach."""

    def test_done_flags_an_isolated_agent_with_tracked_work_and_never_refuses(self):
        self._lead()
        self._child("researcher-notes", file="notes.md", text="read only\n",
                    role="researcher")
        # The report goes through — that is the whole asymmetry with `sb merge`.
        self.b.done("read the code", me="researcher-notes")
        self.assertEqual(self.b.done_flags, ["write-tracked"])
        self.assertEqual(store.get_agent(self.db, "researcher-notes")["state"], "done")

    def test_a_holder_is_not_flagged(self):
        self._lead()
        self._child("worker-one", file="one.txt", text="one\n")
        self.b.done("wrote it", me="worker-one")
        self.assertEqual(self.b.done_flags, [])

    def test_a_shared_child_is_never_flagged_because_attribution_needs_isolation(self):
        """Its writes are on its LEAD's branch, where no `sb merge` for it ever runs and
        nothing can honestly attribute them (§2.1). No branch, no flag."""
        lead = self._lead()
        self._agent("researcher-tab", role="researcher", path=self.lead_path, parent=lead)
        self.b.done("read the code", me="researcher-tab")
        self.assertEqual(self.b.done_flags, [])

    def test_an_isolated_agent_that_wrote_nothing_tracked_is_not_flagged(self):
        """Evidence, not suspicion: a flag every non-holder gets is one they learn to
        ignore."""
        lead = self._lead()
        path = self._worktree("researcher-idle")
        self._agent("researcher-idle", role="researcher", branch="researcher-idle",
                    path=path, parent=lead)
        self.b.done("read the code", me="researcher-idle")
        self.assertEqual(self.b.done_flags, [])

    def test_a_repo_can_narrow_the_shipped_instance_to_one_boundary(self):
        """The table is a config layer like any other, so `!reset` says "exactly this" —
        which is how a repo that wants the merge refusal without the `done` flag says so."""
        self.declare('[capabilities.side_effects]\n"write-tracked" = ["!reset", "merge"]\n')
        self.assertEqual(self.b.side_effect_capabilities(BOUNDARY_MERGE), ["write-tracked"])
        self.assertEqual(self.b.side_effect_capabilities(BOUNDARY_DONE), [])
        self._lead()
        self._child("researcher-notes", file="notes.md", text="read only\n",
                    role="researcher")
        self.b.done("read the code", me="researcher-notes")
        self.assertEqual(self.b.done_flags, [])


class BrokenTableTest(DeclaringFixture, unittest.TestCase):
    """A settings typo must not be able to stop an agent reporting finished. This is not a
    security control, and the failure mode of treating it as one is a fleet that cannot
    speak."""

    def test_an_unreadable_table_costs_the_check_and_not_the_report(self):
        self.declare('[capabilities]\nside_effects = "deploy"\n')
        self.assertEqual(self.b.side_effect_capabilities(BOUNDARY_MERGE), [])
        self._lead()
        self._child("researcher-notes", file="notes.md", text="read only\n",
                    role="researcher")
        self.b.done("read the code", me="researcher-notes")
        self.assertEqual(self.b.done_flags, [])
        kinds = [e["kind"] for e in store.recent_events(self.db, limit=50)]
        self.assertIn("side_effects_unreadable", kinds)


class DeclarationIsDataTest(unittest.TestCase):
    """The shipped table, read the way every other setting is."""

    def test_write_tracked_ships_as_one_instance_at_both_boundaries(self):
        self.assertEqual(roles_mod.side_effect_capabilities(),
                         {"write-tracked": ("merge", "done")})


if __name__ == "__main__":
    unittest.main()
