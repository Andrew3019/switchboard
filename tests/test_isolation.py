"""D2 — isolation per spawn: `delegate(isolation=own|shared)`, gated by `fork`.

Two claims, and the second is the larger one:

1. **The precedence is an ORDERED decision of three rules** (spec §2.2) — a named
   workspace wins, else `inherited AND mints_space(caller)` ⇒ own, else the explicit
   parameter, default `shared`. Each rule is pinned alone, and each PAIRWISE precedence is
   pinned too, because three independent conditions would pass a per-rule test each and
   still decide the overlaps wrong.
2. **ZERO REGRESSION, both directions.** Today's forking spawns still fork, today's
   sharing spawns still share, named workspaces are still honoured. The only new behaviour
   is that isolation is now AVAILABLE to a non-top that holds `fork` — the #163-B unblock.

The nudge that mitigates a big shared fan-out is a guidance-ledger rule exercised in the
broker/guidance tests; these isolation tests keep to placement and capability behavior.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import store  # noqa: E402
from switchboard.broker import (  # noqa: E402
    CAP_FORK, CAP_SPAWN, CAP_WRITE_TRACKED, HUMAN, Broker,
)
from switchboard.herdr import HerdrError  # noqa: E402

from test_workspace import Fixture  # noqa: E402


class _Isolation(Fixture):
    """Helpers shared by the classes below — the fixture is `test_workspace`'s."""

    def _lead_with_fork(self, me: str) -> str:
        """A non-top lead that holds `fork` — which is now just a lead, seeded from its own
        template (D2). Nothing is granted here: needing `sb grant fork` before every
        fan-out is exactly what the seed change removed, and a test that granted it anyway
        would stop noticing if the seed regressed."""
        lead = self.b.delegate("t", topic="a", role="lead", me=me)
        self.assertTrue(self.b.holds_capability(lead, CAP_FORK))
        return lead

    def _spawner_without_fork(self, me: str) -> str:
        """A caller that may spawn and may NOT isolate: a worker, which since 2026-08-31
        arrives holding `spawn` and has never held `fork`. It is not a lead, because a
        lead arrives holding both; what is under test is the gate, not which role trips
        it."""
        w = self.b.delegate("t", topic="fan", role="worker", me=me)
        self.assertTrue(self.b.holds_capability(w, CAP_SPAWN))     # seeded, not granted
        return w

    def _forked(self, agent: str) -> bool:
        """Did this spawn get a space of its own? The branch IS the name when it did."""
        row = store.get_agent(self.db, agent)
        return row["workspace"] == agent and row["branch"] == agent


class PrecedenceTest(_Isolation, unittest.TestCase):
    """The three rules, each alone."""

    def test_rule_1_a_named_workspace_wins_whoever_the_caller_is(self):
        """`--workspace`, `sb start`, a workspace lead's placement: `inherited` is false,
        so the `mints_space` branch is never asked — even of a TOP, which is the caller
        that would otherwise always fork."""
        r = self._open("api", me=self._root("other-top"))
        kid = self.b.delegate("t", topic="t", role="worker", me=self._root(),
                              workspace="api", branch="api", cwd=r["path"])
        self.assertEqual(store.get_agent(self.db, kid)["workspace"], "api")
        self.assertFalse(self._forked(kid))
        self.assertEqual(self.h.calls_of("create_worktree"), ["api"])   # only the join's

    def test_rule_2_inherited_and_mints_space_still_means_own(self):
        """Kept verbatim: a top's inheriting spawn forks, whatever the child's role."""
        kid = self.b.delegate("t", topic="t", role="worker", me=self._root())
        self.assertTrue(self._forked(kid))

    def test_rule_2_keeps_its_inherited_guard_for_a_rowless_caller(self):
        """The human and a caller we hold no row for both mint, for the same reason: no
        space to lend, and the alternative is spawning into whatever checkout `sb` ran
        in."""
        self.assertTrue(self._forked(
            self.b.delegate("t", topic="h", role="worker", me=HUMAN)))
        self.assertTrue(self._forked(
            self.b.delegate("t", topic="s", role="worker", me="nobody")))

    def test_rule_3_is_the_explicit_parameter_and_it_defaults_to_shared(self):
        top = self._root()
        lead = self._lead_with_fork(top)
        shared = self.b.delegate("t", topic="s", role="worker", me=lead)
        asked = self.b.delegate("t", topic="o", role="worker", me=lead,
                                isolation="own")
        self.assertFalse(self._forked(shared))                  # the default
        self.assertEqual(store.get_agent(self.db, shared)["workspace"], lead)
        self.assertTrue(self._forked(asked))

    def test_an_unknown_isolation_value_is_refused_rather_than_guessed(self):
        with self.assertRaises(ValueError) as cm:
            self.b.delegate("t", topic="t", role="worker", me=self._root(),
                            isolation="private")
        self.assertIn("own", str(cm.exception))
        self.assertIn("shared", str(cm.exception))


class OrderedNotIndependentTest(_Isolation, unittest.TestCase):
    """The pairwise precedence — what tells an ORDER from three conditions."""

    def test_a_named_workspace_beats_the_mints_space_branch(self):
        """Rule 1 over rule 2: the caller is a top, and it still does not fork, because it
        already said where this agent goes."""
        r = self._open("api", me=self._root("other-top"))
        kid = self.b.delegate("t", topic="t", role="worker", me=self._root(),
                              workspace="api", branch="api", cwd=r["path"])
        self.assertEqual(store.get_agent(self.db, kid)["workspace"], "api")

    def test_a_named_workspace_beats_an_explicit_isolation_own(self):
        """Rule 1 over rule 3, from a caller that does hold `fork`: placed, not forked."""
        top = self._root()
        r = self._open("api", me=self._root("other-top"))
        kid = self.b.delegate("t", topic="t", role="worker", me=top, isolation="own",
                              workspace="api", branch="api", cwd=r["path"])
        self.assertEqual(store.get_agent(self.db, kid)["workspace"], "api")
        self.assertFalse(self._forked(kid))

    def test_the_mints_space_branch_beats_an_explicit_isolation_shared(self):
        """Rule 2 over rule 3, and this is what "kept verbatim" means: a top's spawn forks
        whether or not `shared` was asked for. Typing `--isolation shared` at a top cannot
        put a child in the human's own checkout."""
        kid = self.b.delegate("t", topic="t", role="worker", me=self._root(),
                              isolation="shared")
        self.assertTrue(self._forked(kid))

    def test_the_predicate_itself_answers_in_that_order(self):
        """The same three rules asked of `isolates` directly, which is where the order
        lives — a named workspace (`inherited=False`) answers False for a top asking for
        `own`, and a top answers True while asking for `shared`."""
        top = self._root()
        self.assertFalse(self.b.isolates(top, inherited=False, isolation="own",
                                         role="worker"))
        self.assertTrue(self.b.isolates(top, inherited=True, isolation="shared",
                                        role="worker"))
        lead = self.b.delegate("t", topic="a", role="lead", me=top)
        self.assertFalse(self.b.isolates(lead, inherited=True, isolation="shared",
                                         role="worker"))
        self.assertTrue(self.b.isolates(lead, inherited=True, isolation="own",
                                        role="worker"))
        # And holding `fork` is NOT what answers rule 2: this lead holds it and still
        # shares by default, which is the whole reason seeding it is safe.
        self.assertTrue(self.b.holds_capability(lead, CAP_FORK))


class ReviewerNeverForksTest(_Isolation, unittest.TestCase):
    """Rule 1a: a reviewer reviews existing work, so it joins the caller's checkout rather
    than forking an empty worktree with nothing in it to review — even under a top, the one
    caller rule 2 forks unconditionally."""

    def test_a_tops_reviewer_joins_its_checkout_while_a_worker_forks(self):
        """The bug: a top's reviewer forked off `origin/main`, away from the very changes
        it was spawned to read. A worker spawned the same way still forks — the carve-out
        is the reviewer's alone."""
        top = self._root()
        worker = self.b.delegate("t", topic="w", role="worker", me=top)
        reviewer = self.b.delegate("t", topic="r", role="reviewer", me=top)
        self.assertTrue(self._forked(worker))
        self.assertFalse(self._forked(reviewer))

    def test_a_workers_own_reviewer_joins_the_workers_worktree(self):
        """WHAT SEEDING `spawn` TO EVERY WRITING LEAF IS FOR (2026-08-31). A worker holds
        `spawn` with no `sb grant` anywhere, so the review of its change is put up BY the
        worker — and rule 1a then joins that reviewer to the WORKER's checkout, which is
        the one the change is in.

        Handed back up instead, the same rule fires with the wrong caller: the parent
        spawns the reviewer, so the reviewer joins the PARENT's checkout, and under a top
        (which mints its own space and has none to lend) that is a tree with none of the
        work in it. The mechanism was already right; what was missing was the worker
        being able to be the caller."""
        top = self._root()
        worker = self.b.delegate("t", topic="w", role="worker", me=top)
        self.assertTrue(self.b.holds_capability(worker, CAP_SPAWN))
        reviewer = self.b.delegate("t", topic="rv", role="reviewer", me=worker)
        self.assertFalse(self._forked(reviewer))
        w_row = store.get_agent(self.db, worker)
        r_row = store.get_agent(self.db, reviewer)
        self.assertEqual((r_row["workspace"], r_row["branch"], r_row["cwd"]),
                         (w_row["workspace"], w_row["branch"], w_row["cwd"]))
        # And it comes out able to make its scoped minor fixes: the worker holds
        # `write-tracked`, so the ∩-rule passes the reviewer template's copy of it down.
        self.assertIn(CAP_WRITE_TRACKED, store.held_capabilities(self.db, reviewer))

    def test_the_predicate_carves_out_only_rule_2_not_rule_1_or_3(self):
        """A reviewer skips rule 2's automatic fork but still honours an explicit named
        workspace (rule 1) and an explicit `isolation=own` (rule 3)."""
        top = self._root()
        # Rule 2 is what is carved out: a top's inheriting reviewer does not fork.
        self.assertFalse(self.b.isolates(top, inherited=True, isolation="shared",
                                         role="reviewer"))
        # Rule 1 still wins: a named workspace is not inherited, so it is honoured.
        self.assertFalse(self.b.isolates(top, inherited=False, isolation="shared",
                                         role="reviewer"))
        # Rule 3 is still reachable: an explicit `own` isolates the reviewer anyway.
        self.assertTrue(self.b.isolates(top, inherited=True, isolation="own",
                                        role="reviewer"))


class TheForkGateTest(_Isolation, unittest.TestCase):
    """`isolation=own` is gated on `fork`, read off the CALLER."""

    def test_a_non_top_holding_fork_can_isolate_its_child(self):
        """THE #163-B UNBLOCK: isolation is available below the top for the first time."""
        lead = self._lead_with_fork(self._root())
        kid = self.b.delegate("t", topic="w", role="worker", me=lead, isolation="own")
        self.assertTrue(self._forked(kid))
        self.assertIn(kid, self.h.calls_of("create_worktree"))
        self.assertNotEqual(store.get_agent(self.db, kid)["cwd"],
                            store.get_agent(self.db, lead)["cwd"])

    def test_a_caller_without_fork_is_refused_and_told_what_to_do(self):
        fanner = self._spawner_without_fork(self._lead_with_fork(self._root()))
        with self.assertRaises(ValueError) as cm:
            self.b.delegate("t", topic="w", role="worker", me=fanner, isolation="own")
        self.assertIn("fork", str(cm.exception))
        self.assertIn("sb grant", str(cm.exception))
        self.assertIsNone(store.get_agent(self.db, "worker-w"))     # nothing spawned

    def test_the_gate_reads_the_caller_not_the_child(self):
        """A `fork`-less caller spawning a LEAD — a role that does hold `fork` — is still
        refused: the question is who is doing the asking, not what is being spawned."""
        fanner = self._spawner_without_fork(self._lead_with_fork(self._root()))
        with self.assertRaises(ValueError):
            self.b.delegate("t", topic="b", role="lead", me=fanner, isolation="own")

    def test_isolation_is_not_derived_from_the_capability_set_either_way(self):
        """Holding `write-tracked` does not isolate you, and being isolated grants
        nothing: the isolated child below holds exactly a worker's seeded set."""
        lead = self._lead_with_fork(self._root())
        writer = self.b.delegate("t", topic="w", role="worker", me=lead)   # write-tracked
        self.assertFalse(self._forked(writer))                             # still shared
        iso = self.b.delegate("t", topic="r", role="researcher", me=lead,
                              isolation="own")                             # read-only
        self.assertTrue(self._forked(iso))
        self.assertFalse(self.b.holds_capability(iso, CAP_FORK))


class TheLeadSeedTest(_Isolation, unittest.TestCase):
    """D2 stops `fork` being subtracted from every non-top seed
    (`roles.template_capabilities`), so a LEAD arrives able to isolate.

    Safe only because of this unit's other half: the fork decision reads the `is_top` stamp
    (rule 2) and rule 3 defaults to `shared`, so holding `fork` changes what a lead may ASK
    for and nothing about what it gets by default. Before D2 the same seed would have
    minted a new workspace for every one of its spawns.
    """

    def test_a_default_ungranted_lead_can_isolate_a_child(self):
        """No `sb grant` anywhere: needing one before every fan-out is the bureaucracy the
        capability set exists to remove."""
        lead = self.b.delegate("t", topic="a", role="lead", me=self._root())
        self.assertTrue(self.b.holds_capability(lead, CAP_FORK))    # from the seed
        kid = self.b.delegate("t", topic="w", role="worker", me=lead, isolation="own")
        self.assertTrue(self._forked(kid))
        self.assertNotEqual(store.get_agent(self.db, kid)["cwd"],
                            store.get_agent(self.db, lead)["cwd"])

    def test_that_same_lead_still_shares_by_default(self):
        """The regression this seed would have been, if D2 had only added the parameter."""
        lead = self.b.delegate("t", topic="a", role="lead", me=self._root())
        kid = self.b.delegate("t", topic="w", role="worker", me=lead)
        self.assertFalse(self._forked(kid))
        row, lrow = store.get_agent(self.db, kid), store.get_agent(self.db, lead)
        self.assertEqual((row["workspace"], row["branch"], row["cwd"]),
                         (lrow["workspace"], lrow["branch"], lrow["cwd"]))
        self.assertEqual(self.h.calls_of("create_worktree"), [lead])   # one fork, the lead's

    def test_only_a_role_whose_template_names_fork_gains_anything(self):
        """Every other shipped bundle is untouched — none of them named `fork`."""
        for role in ("dispatcher", "worker", "researcher", "reviewer", "qa"):
            with self.subTest(role=role):
                self.assertNotIn(CAP_FORK, self.b.seed_for(role, is_top=False))
        self.assertIn(CAP_FORK, self.b.seed_for("lead", is_top=False))


class ZeroRegressionTest(_Isolation, unittest.TestCase):
    """Both directions, with no isolation argument anywhere — the shape of every spawn
    that exists today."""

    def test_todays_spawns_fork_and_share_exactly_as_before(self):
        top = self._root()
        lead = self.b.delegate("t", topic="a", role="lead", me=top)     # top → lead: forks
        worker = self.b.delegate("t", topic="w", role="worker", me=lead)  # lead → worker
        nested = self.b.delegate("t", topic="n", role="lead", me=lead)    # and a subtree
        deep = self.b.delegate("t", topic="d", role="worker", me=nested)
        self.assertTrue(self._forked(lead))
        for kid in (worker, nested, deep):
            row = store.get_agent(self.db, kid)
            self.assertEqual(row["workspace"], lead)
            self.assertEqual(row["branch"], lead)
            self.assertEqual(row["cwd"], store.get_agent(self.db, lead)["cwd"])
        self.assertEqual(self.h.calls_of("create_worktree"), [lead])   # exactly one fork

    def test_a_fork_that_fails_still_refuses_the_spawn_with_no_fallback(self):
        """Unchanged, and now reached by a wider audience — a non-top asking for `own`
        lands on exactly this path."""
        from switchboard.broker import ForkFailed
        lead = self._lead_with_fork(self._root())
        self.h.create_worktree = None                   # an adapter that cannot fork
        with self.assertRaises(ForkFailed):
            self.b.delegate("t", topic="w", role="worker", me=lead, isolation="own")
        self.assertIsNone(store.get_agent(self.db, "worker-w"))


class NonPrimaryCallerTest(_Isolation, unittest.TestCase):
    """WHERE the worktree is created FROM — the half of `--isolation own` a live
    shakedown found broken (`.switchboard/notes/qa-shakedown-live-fleet.md` §2).

    herdr's `create_worktree`/`open_worktree` take `--cwd` to name WHICH REPO, and it
    must be that repo's PRIMARY checkout: a linked worktree is refused outright with
    `[linked_worktree_source] New and open worktree actions start from the repo parent
    workspace.` The broker used to pass `self.repo`, which is `Path.cwd()` — the calling
    process's own directory. A lead sitting in its own linked worktree (every lead below
    the top) therefore could not fork an isolated child at all, which contradicts "any
    agent can get its own worktree for a job, not just the top". These pin the cwd, not
    the isolation decision: nothing here changes WHO forks or what they fork off.
    """

    def _linked(self) -> tuple[Path, Path]:
        """A real repo plus a linked worktree of it — `git worktree list` is the only
        thing that can tell one from the other, so the repo has to be real."""
        main = self._git_repo()
        wt = self.repo / "lead-checkout"
        subprocess.run(["git", "worktree", "add", "-q", "-b", "lead-checkout", str(wt)],
                       cwd=main, capture_output=True)
        return main.resolve(), wt.resolve()

    def _cwds(self) -> list[str]:
        """Record the `--cwd` of every fork, without teaching the fake anything: the
        existing adapter is wrapped, exactly as the other tests here override it."""
        real, seen = self.h.create_worktree, []

        def recording(branch, **kw):
            seen.append(kw.get("cwd"))
            return real(branch, **kw)

        self.h.create_worktree = recording
        return seen

    def test_a_lead_in_its_own_worktree_forks_from_the_primary_checkout(self):
        """The repro. The lead's own process stands in a linked worktree; the fork must
        still name the repo's primary checkout. Before the fix this was the linked
        worktree's path, which is the value herdr refuses."""
        main, wt = self._linked()
        lead = self._lead_with_fork(self._root())
        theirs = Broker(self.db, self.h, repo=wt)      # the lead's OWN process
        seen = self._cwds()
        kid = theirs.delegate("t", topic="child", role="worker", me=lead,
                              isolation="own")
        self.assertTrue(self._forked(kid))
        self.assertEqual([Path(c).resolve() for c in seen], [main])

    def test_a_herdr_that_refuses_a_linked_source_now_spawns_the_child(self):
        """The failure as herdr actually delivers it — the refusal from the shakedown,
        raised by a stand-in that checks the cwd the way herdr does. Before the fix this
        came back as `ForkFailed` and no child at all."""
        main, wt = self._linked()
        lead = self._lead_with_fork(self._root())
        real = self.h.create_worktree

        def strict(branch, **kw):
            if Path(kw.get("cwd") or "").resolve() != main:
                raise HerdrError("linked_worktree_source",
                                 "New and open worktree actions start from the repo "
                                 "parent workspace.")
            return real(branch, **kw)

        self.h.create_worktree = strict
        theirs = Broker(self.db, self.h, repo=wt)
        kid = theirs.delegate("t", topic="child", role="worker", me=lead,
                              isolation="own")
        self.assertTrue(self._forked(kid))
        self.assertEqual(store.get_agent(self.db, kid)["branch"], kid)

    def test_the_primary_checkout_caller_is_unchanged(self):
        """No regression to the one case that always worked: a caller already standing in
        the primary checkout still names it."""
        main = self._git_repo().resolve()
        lead = self._lead_with_fork(self._root())
        theirs = Broker(self.db, self.h, repo=main)
        seen = self._cwds()
        theirs.delegate("t", topic="child", role="worker", me=lead, isolation="own")
        self.assertEqual([Path(c).resolve() for c in seen], [main])


if __name__ == "__main__":
    unittest.main()
