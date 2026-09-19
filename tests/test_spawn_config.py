"""#328 — one `sb delegate` call sets a child's WHOLE initial configuration.

Three claims, and they are three because the spec's sentence is three promises in one
(migration_sb_v2.md §11, §8):

1. **One atomic call.** Role, model, presets, placement, assignment, handoff, Step and Plan
   ownership all in one `sb delegate`. "The caller must never need a sequence of spawn →
   set role → set model → attach preset → assign Plan → assign Step → configure worktree →
   send initial instructions." So the test that matters most is the one that types all of
   it at once and then reads every one of those facts back.
2. **`--assign-step` is about the SPAWNEE.** An unowned Step assigns freely; an owned one
   needs `--steal`, which records the move and tells the previous owner. The invariant
   underneath is "exactly one accountable owner", so the refusal is pinned as hard as the
   assignment — and pinned to happen BEFORE anything spawns, because the alternative is a
   live agent with no work.
3. **Placement is the delegator's choice, and today's default is untouched.** `--worktree`
   is one flag over the two that already existed; the regression that would matter is a
   spawn that used to share suddenly forking, so the default is pinned by itself.

Everything runs through `cli.main` against `test_workspace.FakeHerdr`, in `PlansSandbox` —
the spawn and the plan have to be the real ones for this to be testing anything: the whole
subject is sb reaching a plugin's Step through a seam, and a fake either side of that seam
would leave the seam untested.

Unproven here: that the steal's message is DELIVERED to a running agent's context rather
than merely written to its mailbox (the doorbell is herdr's, and this herdr is fake), and
that anything yet refuses a `done` from an agent that owns a Plan — the gate that consumes
`--own-plan` is #329's and was cut from that issue's lean scope.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from switchboard import cli  # noqa: E402
from switchboard import store  # noqa: E402
from switchboard.herdr import section_body  # noqa: E402

from test_plans_plugin import PlansSandbox, _create, _same_id  # noqa: E402
from test_workspace import FakeHerdr  # noqa: E402


class SpawnConfigSandbox(PlansSandbox):
    """A sandbox that can both spawn and hold a plan, which is the whole point."""

    def setUp(self) -> None:
        super().setUp()
        self.h = FakeHerdr(self.repo / "worktrees")

    def spawn(self, *argv) -> tuple[int, str, str]:
        with mock.patch.object(cli, "Herdr", lambda **kw: self.h):
            return self.sb("delegate", *argv)

    def spawned(self, *argv) -> dict:
        """One spawn that must succeed, as its `--json` receipt."""
        with mock.patch.object(cli, "Herdr", lambda **kw: self.h):
            code, out, err = self.sb("delegate", *argv, "--json")
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def plan(self, *steps: str) -> dict:
        return self.data(*_create("a job", *steps))

    def step(self, sid: str, plan: str = "p-1") -> dict:
        return next(s for p in self._doc()["plans"] for s in p["steps"]
                    if _same_id(s, sid) and p["id"] == plan)

    def row(self, name: str) -> dict:
        db = store.connect(self.repo)
        try:
            return dict(store.get_agent(db, name))
        finally:
            db.close()

    def live(self, *names: str) -> None:
        """Agent rows for the agents a test needs to already exist — a previous owner."""
        db = store.connect(self.repo)
        for name in names:
            store.create_agent(db, name=name, role="worker", cwd=str(self.repo))
            store.set_state(db, name, "working")
        db.close()

    def events(self, kind: str) -> list[dict]:
        db = store.connect(self.repo)
        try:
            return [dict(r) for r in db.execute(
                "SELECT * FROM events WHERE kind = ? ORDER BY id", (kind,)).fetchall()]
        finally:
            db.close()


class OneCallTest(SpawnConfigSandbox):
    """Claim 1: everything §11 lists, typed once, and every fact read back."""

    def test_one_call_sets_role_model_presets_placement_assignment_handoff_step_and_plan(self):
        """THE WHOLE SENTENCE, in one command. Read back from four different places on
        purpose — the agent row, the prompt herdr was handed, the first message it was
        sent, and the plan file — because "one call configured all of it" is a claim about
        those four agreeing, and a test that read one of them would pass on a spawn that
        had dropped the other three."""
        self.plan("shape the work", "build the thing")
        self.as_agent("lead-1")
        self.live("lead-1")
        got = self.spawned(
            "--assignment", "build the thing properly",
            "--role", "worker", "--model", "careful",
            "--preset", "be brief", "--preset", "and correct",
            "--worktree", "same",
            "--handoff", "the API client is half written in client.py",
            "--assign-step", "step-2", "--own-plan", "p-1",
            "--name", "the thing")
        name = got["name"]

        row = self.row(name)
        self.assertEqual(row["role"], "worker")
        self.assertEqual(row["tier"], "careful")          # --model, recorded on the claim
        self.assertIsNone(row["branch"])                  # --worktree same: no fork

        # The presets are in the standing payload, under their own labels (#327).
        prompts = [section_body(p) for p in self.h.started[-1]["prompts"]]
        self.assertTrue(any("be brief" in p for p in prompts), prompts)
        self.assertTrue(any("and correct" in p for p in prompts), prompts)

        # The assignment and the handoff are the FIRST MESSAGE, not the standing prompt —
        # §11 layer 3, and #327's separation. Both in it, and neither in the payload.
        first = [text for who, text in self.h.prompts if who == name][-1]
        self.assertIn("build the thing properly", first)
        self.assertIn("client.py", first)
        self.assertFalse(any("client.py" in p for p in prompts), prompts)

        # The Step is the spawnee's, and so is the Plan, end to end.
        self.assertEqual(self.step("step-2")["owner"], name)
        self.assertEqual(self._doc()["plans"][0]["owner"], name)
        self.assertEqual(got["assigned"]["step"]["step"], "step-2")
        self.assertEqual(got["assigned"]["plan"]["owner"], name)

    def test_preset_is_the_same_flag_as_with_and_they_accumulate_together(self):
        """§11 spells it `--preset`; this repo shipped `--with`. One dest, so a caller
        mixing them gets four presets rather than two flags fighting over one list."""
        self.as_agent("lead-1")
        self.live("lead-1")
        got = self.spawned("do it", "--with", "alpha", "--preset", "beta", "--name", "x y")
        prompts = [section_body(p) for p in self.h.started[-1]["prompts"]]
        self.assertTrue(any("alpha" in p for p in prompts), prompts)
        self.assertTrue(any("beta" in p for p in prompts), prompts)
        self.assertTrue(got["name"])

    def test_assignment_beside_the_positional_task_is_refused(self):
        """Two tasks in one call is a caller that has said two things, and picking one
        silently is how a child does the job its parent did not send."""
        self.as_agent("lead-1")
        self.live("lead-1")
        code, _, err = self.spawn("do this", "--assignment", "no, this", "--name", "x y")
        self.assertEqual(code, 2)          # a usage error, like argparse's own
        self.assertIn("same thing", err)
        self.assertEqual(self.h.started, [])


class AssignStepTest(SpawnConfigSandbox):
    """Claim 2: the Step the spawnee takes, and the one invariant under it."""

    def test_an_unowned_step_is_assigned_to_the_spawnee_not_to_the_caller(self):
        """"It is about the spawnee, not the caller" (§11). The changelog says both: the
        caller is `by`, the child is the owner the move names."""
        self.plan("shape the work", "review it")
        self.as_agent("lead-1")
        self.live("lead-1")
        name = self.spawned("review it", "--assign-step", "step-2",
                            "--name", "the review")["name"]
        self.assertEqual(self.step("step-2")["owner"], name)
        entry = self.data("plugin", "plans", "changelog", "p-1")[-1]
        self.assertEqual(entry["action"], "take")
        self.assertEqual(entry["by"], "lead-1")
        self.assertIn(f"→ {name}", entry["detail"])
        self.assertEqual(len(self.events("step_assigned")), 1)

    def test_an_owned_step_is_refused_before_anything_spawns(self):
        """The preflight is the whole reason the check is a separate call: the refusals
        `--assign-step` can earn are the ones a caller fixes by retyping, and paying for
        one with a pane, a worktree and an agent with nothing to do is what this removes.
        So the assertion that matters is not the message — it is that nothing started."""
        self.plan("shape the work", "build it")
        self.live("w1", "lead-1")
        self.as_agent("w1")
        self.ok("plugin", "plans", "take", "step-2")
        self.as_agent("lead-1")
        code, _, err = self.spawn("build it", "--assign-step", "step-2", "--name", "the build")
        self.assertEqual(code, 1)
        self.assertIn("owned by w1", err)
        self.assertIn("--steal", err)
        self.assertEqual(self.h.started, [], "a refused assignment still spawned an agent")
        self.assertEqual(self.step("step-2")["owner"], "w1")

    def test_a_step_that_is_not_a_step_is_refused_before_anything_spawns(self):
        self.plan("shape the work")
        self.as_agent("lead-1")
        self.live("lead-1")
        code, _, err = self.spawn("go", "--assign-step", "step-9", "--name", "a thing")
        self.assertEqual(code, 1)
        self.assertEqual(self.h.started, [])
        self.assertIn("step-9", err)

    def test_steal_moves_the_step_tells_the_previous_owner_and_records_the_event(self):
        """A steal is never silent, and "never silent" is two records and a message: the
        plan's own changelog action, sb's event, and a `sb tell` to the agent that lost
        it naming the step and the agent that now has it — the SPAWNEE, not the caller,
        because the previous owner's question is who holds its step now."""
        self.plan("shape the work", "build it")
        self.live("w1", "lead-1")
        self.as_agent("w1")
        self.ok("plugin", "plans", "take", "step-2")
        self.as_agent("lead-1")
        got = self.spawned("build it", "--assign-step", "step-2", "--steal",
                           "--name", "the build")
        name = got["name"]
        self.assertEqual(self.step("step-2")["owner"], name)
        self.assertEqual(self.data("plugin", "plans", "changelog", "p-1")[-1]["action"],
                         "steal")

        events = self.events("step_stolen")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["step_id"], "step-2")
        self.assertEqual(events[0]["agent"], name)

        db = store.connect(self.repo)
        told = [m["body"] for m in store.unread_for(db, "w1", mark=False)]
        db.close()
        self.assertTrue(any("step-2" in b and name in b for b in told), told)

    def test_handing_over_a_step_you_own_needs_no_steal_and_tells_nobody(self):
        """THE COMMONEST DELEGATION THERE IS: a lead owns `Implement` and spawns a worker
        to do it. `--steal` is a safeguard for an owner that did not consent, and the owner
        here is the agent typing the command — so requiring it would be the wrong word for
        the event, and the tell it triggers would be the caller mailing itself."""
        self.plan("shape the work", "build it")
        self.live("lead-1")
        self.as_agent("lead-1")
        self.ok("plugin", "plans", "take", "step-2")
        name = self.spawned("build it", "--assign-step", "step-2",
                            "--name", "the build")["name"]
        self.assertEqual(self.step("step-2")["owner"], name)
        self.assertEqual(self.data("plugin", "plans", "changelog", "p-1")[-1]["action"],
                         "take")                      # a handoff, not a steal
        self.assertEqual(self.events("step_stolen"), [])
        db = store.connect(self.repo)
        told = [m["body"] for m in store.unread_for(db, "lead-1", mark=False)]
        db.close()
        self.assertEqual(told, [], "the caller was mailed about its own handoff")

    def test_assigning_a_step_does_not_make_the_delegator_a_contributor_to_it(self):
        """#321 reads the changelog to decide who may review. A take NAMES its new owner in
        the owner move, so counting `by` as well made every delegator a recorded
        contributor to the step it handed out — and a reviewer that spawns a fixer would
        then be refused the review it was spawned for. The spawnee is still judged, and
        still fresh."""
        self.plan("shape the work", "build it", "check it")
        # `create` does not parse a `Name:kind` suffix, so the review step's kind is set
        # the way a lead shapes a plan — in the file. The guard is keyed on kind and never
        # on a display name, which is exactly what this has to be true of.
        self.edit_step("step-3", kind="review")
        self.live("lead-1")
        self.as_agent("lead-1")
        name = self.spawned("build it", "--assign-step", "step-2",
                            "--name", "the build")["name"]
        self.assertEqual(self.step("step-2")["owner"], name)
        # The delegator may still take the review: it assigned the work, it did not do it.
        self.ok("plugin", "plans", "take", "step-3")
        self.assertEqual(self.step("step-3")["owner"], "lead-1")
        # And the agent that actually owns the implementation still cannot.
        code, _, err = self.sb("plugin", "plans", "release", "step-3")
        self.assertEqual(code, 0, err)
        self.as_agent(name)
        code, _, err = self.sb("plugin", "plans", "take", "step-3")
        self.assertEqual(code, 1)
        self.assertIn("review is independent by default", err)

    def test_an_assignment_that_fails_after_the_spawn_names_the_child_and_exits_one(self):
        """The race the two-call split leaves open: the step was free at the check and
        gone by the assignment. There is an agent up and it owns nothing, so the caller is
        told which agent, what went wrong and how to finish by hand — and the exit code
        says the call did not do what was asked."""
        self.plan("shape the work", "build it")
        self.live("lead-1")
        self.as_agent("lead-1")
        boom = mock.patch.object(cli.assign_mod, "apply",
                                 side_effect=cli.assign_mod.AssignmentRefused("gone"))
        with boom:
            code, out, err = self.spawn("build it", "--assign-step", "step-2",
                                        "--name", "the build")
        self.assertEqual(code, 1)
        said = out + err
        self.assertIn("gone", said)
        self.assertIn("worker-the-build", said)
        self.assertIn("--for worker-the-build", said)
        self.assertEqual(len(self.events("assign_failed")), 1)
        self.assertIsNone(self.step("step-2")["owner"])
        self.assertEqual(self.row("worker-the-build")["name"], "worker-the-build")

    def test_a_step_pre_staged_onto_the_spawnee_is_a_clean_no_op(self):
        """THE GAP-REVIEW BUG. `take <step> --for <name>` pre-stages a step onto an agent
        that does not exist yet (#314 blesses it), and the spawn that then creates that
        agent was asked for the end state that already holds.

        It used to report a move that never happened: the receipt printed `None/step-1`,
        sb wrote a `step_stolen` event with a NULL `plan_id` — so no `history(plan_id=…)`
        read could find it — and the plan's own changelog said nothing had happened. The
        two records the design calls complementary contradicted each other.

        With `--steal` too, and that is the half that bit: a steal of a step nobody else
        holds is not a steal.
        """
        for flags in ([], ["--steal"]):
            with self.subTest(flags=flags or "none"):
                self.setUp()
                self.plan("shape the work", "build it")
                self.live("lead-1")
                self.as_agent("lead-1")
                self.ok("plugin", "plans", "take", "step-1", "--for", "worker-the-fix")
                got = self.spawned("fix it", "--name", "the fix",
                                   "--assign-step", "step-1", *flags)
                self.assertEqual(got["name"], "worker-the-fix")
                self.assertEqual(self.step("step-1")["owner"], "worker-the-fix")

                # NOTHING MOVED, so nothing claims it did — in either record.
                self.assertEqual(self.events("step_stolen"), [])
                self.assertEqual(self.events("step_assigned"), [])
                self.assertEqual([e["action"] for e in
                                  self.data("plugin", "plans", "changelog", "p-1")],
                                 ["create", "take"])

                # And the receipt names the real plan, not a null one.
                said = got["assigned"]["step"]
                self.assertEqual(said["plan"], "p-1")
                self.assertEqual(said["step"], "step-1")
                self.assertTrue(said["already_owned"])
                self.assertIsNone(said["notified"])

    def test_no_assignment_event_is_ever_written_without_the_plan_it_is_about(self):
        """The shape the NULL `plan_id` took, pinned as a property rather than as one
        case: an event nothing can find by its plan is an event that cannot be
        contradicted by the plan it claims to describe."""
        self.plan("shape the work", "build it")
        self.live("lead-1", "w1")
        self.as_agent("w1")
        self.ok("plugin", "plans", "take", "step-2")
        self.as_agent("lead-1")
        self.ok("plugin", "plans", "take", "step-1", "--for", "worker-pre-staged")
        self.spawned("a", "--name", "one", "--assign-step", "step-2", "--steal")
        self.spawned("b", "--name", "pre staged", "--assign-step", "step-1")
        for kind in ("step_assigned", "step_stolen", "plan_owned"):
            for e in self.events(kind):
                with self.subTest(kind=kind):
                    self.assertTrue(e["plan_id"], f"{kind} written with no plan: {dict(e)}")

    def test_the_preflight_agrees_with_the_assignment_on_a_pre_staged_step(self):
        """The reverse gap: the check used to refuse what the assignment would accept, and
        the refusal told the caller to steal the step from the agent it was creating. sb
        composes the prospective name before it spawns, so both ends ask the same
        question — and a step pre-staged onto somebody ELSE is still refused."""
        self.plan("shape the work", "build it")
        self.live("lead-1")
        self.as_agent("lead-1")
        self.ok("plugin", "plans", "take", "step-1", "--for", "worker-the-fix")
        self.assertTrue(self.spawned("fix it", "--name", "the fix",
                                     "--assign-step", "step-1")["name"])

        self.ok("plugin", "plans", "take", "step-2", "--for", "somebody-else")
        code, _, err = self.spawn("build it", "--name", "the build",
                                  "--assign-step", "step-2")
        self.assertEqual(code, 1)
        self.assertIn("owned by somebody-else", err)
        self.assertEqual(len(self.h.started), 1)      # only the first spawn ever ran

    def test_steal_without_a_step_to_steal_is_refused(self):
        self.as_agent("lead-1")
        self.live("lead-1")
        code, _, err = self.spawn("go", "--steal", "--name", "a thing")
        self.assertEqual(code, 2)
        self.assertIn("--assign-step", err)


class OwnPlanTest(SpawnConfigSandbox):
    """`--own-plan`: the accountable owner, recorded. What CONSUMES it is #329's."""

    def test_own_plan_records_the_spawnee_as_the_plans_end_to_end_owner(self):
        self.plan("shape the work")
        self.as_agent("lead-1")
        self.live("lead-1")
        name = self.spawned("land it", "--own-plan", "p-1", "--name", "the plan")["name"]
        self.assertEqual(self._doc()["plans"][0]["owner"], name)
        self.assertIn("accountable for it landing",
                      self.ok("plugin", "plans", "show", "p-1"))
        self.assertEqual(self.data("plugin", "plans", "changelog", "p-1")[-1]["action"],
                         "own")
        self.assertEqual(len(self.events("plan_owned")), 1)

    def test_the_owner_is_system_held_against_a_hand_edit(self):
        """A step's `owner` is held, and so is this: ownership changes hands through a
        verb that records the move, so a document handing back a different one would be
        ownership changing with nothing in the changelog saying it did."""
        self.plan("shape the work")
        self.as_agent("lead-1")
        self.live("lead-1")
        name = self.spawned("land it", "--own-plan", "p-1", "--name", "the plan")["name"]
        doc = self.data("plugin", "plans", "show", "p-1", "--full", "--json")
        doc["owner"] = "somebody-else"
        path = Path(self.tmp.name) / "edit.json"
        path.write_text(json.dumps(doc))
        self.ok("plugin", "plans", "edit", "p-1", "--file", str(path),
                "--version", doc["version"])
        self.assertEqual(self._doc()["plans"][0]["owner"], name)

    def test_taking_a_plan_from_another_owner_needs_steal_and_tells_them(self):
        """Symmetric with a Step's ownership, and for the same reason: end-to-end
        ownership is an accountability, and moving one silently means two agents each
        believe they are accountable — or nobody does."""
        self.plan("shape the work")
        self.live("lead-1", "w1")
        self.as_agent("lead-1")
        first = self.spawned("land it", "--own-plan", "p-1", "--name", "the plan")["name"]
        code, _, err = self.spawn("take over", "--own-plan", "p-1", "--name", "a retry")
        self.assertEqual(code, 1)
        self.assertIn("already", err)
        self.assertIn("--steal", err)
        self.assertEqual(self.h.started[-1]["name"], first)   # nothing new spawned
        self.assertEqual(self._doc()["plans"][0]["owner"], first)

        second = self.spawned("take over", "--own-plan", "p-1", "--steal",
                              "--name", "a retry")["name"]
        self.assertEqual(self._doc()["plans"][0]["owner"], second)
        db = store.connect(self.repo)
        told = [m["body"] for m in store.unread_for(db, first, mark=False)]
        db.close()
        self.assertTrue(any("p-1" in b and second in b for b in told), told)

    def test_handing_over_a_plan_you_own_needs_no_steal(self):
        """The same handoff rule a Step has: the only agent that could be told is the one
        typing the command."""
        self.plan("shape the work")
        self.live("lead-1")
        self.as_agent("lead-1")
        self._save({**self._doc(), "plans": [{**self._doc()["plans"][0],
                                              "owner": "lead-1"}]})
        name = self.spawned("land it", "--own-plan", "p-1", "--name", "the plan")["name"]
        self.assertEqual(self._doc()["plans"][0]["owner"], name)
        db = store.connect(self.repo)
        self.assertEqual(store.unread_for(db, "lead-1", mark=False), [])
        db.close()

    def test_a_plan_that_is_not_there_is_refused_before_anything_spawns(self):
        self.as_agent("lead-1")
        self.live("lead-1")
        code, _, err = self.spawn("go", "--own-plan", "p-9", "--name", "a thing")
        self.assertEqual(code, 1)
        self.assertEqual(self.h.started, [])
        self.assertIn("p-9", err)


class NoProviderTest(SpawnConfigSandbox):
    """The other half of "the seam fails loudly": a repo where nothing owns Steps.

    `plans` ships enabled, so this is the repo that turned it off — and the flag must then
    refuse rather than spawn an agent and quietly assign nothing, which is the failure the
    obligations seam is allowed to have and this one is not.
    """

    def setUp(self) -> None:
        super().setUp()
        # `"!reset"`, not `[]`: arrays JOIN (config merge rule 3), so an empty list would
        # keep every shipped plugin and this class would be testing nothing.
        (self.sw / "plugins.toml").write_text('enabled = ["!reset"]\n')

    def test_assign_step_with_no_plugin_that_owns_steps_refuses_and_spawns_nothing(self):
        self.as_agent("lead-1")
        self.live("lead-1")
        code, _, err = self.spawn("go", "--assign-step", "step-1", "--name", "a thing")
        self.assertEqual(code, 1)
        self.assertEqual(self.h.started, [])
        self.assertIn("no enabled plugin owns Plan Steps", err)

    def test_a_spawn_that_assigns_nothing_is_untouched_by_the_seam(self):
        """The cost of the seam on every OTHER spawn is nothing — it is not consulted."""
        self.as_agent("lead-1")
        self.live("lead-1")
        self.assertTrue(self.spawned("go", "--name", "a thing")["name"])


class PlacementTest(SpawnConfigSandbox):
    """Claim 3: the delegator chooses, and the choice it does not make is unchanged."""

    def test_the_default_placement_is_still_the_callers_own_checkout(self):
        """THE REGRESSION THAT WOULD MATTER. `--worktree` exists now; a spawn that names
        no placement must still land exactly where it always did — a tab in the caller's
        space, no fork, no branch of its own."""
        self.as_agent("lead-1")
        self.live("lead-1")
        row = self.row(self.spawned("do it", "--name", "a thing")["name"])
        self.assertIsNone(row["branch"])
        self.assertEqual(row["cwd"], str(self.repo))

    def test_worktree_same_is_that_default_said_out_loud(self):
        self.as_agent("lead-1")
        self.live("lead-1")
        row = self.row(self.spawned("do it", "--worktree", "same",
                                    "--name", "a thing")["name"])
        self.assertIsNone(row["branch"])

    def test_worktree_new_forks_a_worktree_and_branch_of_its_own(self):
        self.as_agent("lead-1")
        self.live("lead-1")
        name = self.spawned("do it", "--worktree", "new", "--name", "a thing")["name"]
        row = self.row(name)
        self.assertEqual(row["branch"], name)
        self.assertEqual(row["workspace"], name)

    def test_worktree_names_an_existing_workspace_to_join(self):
        """§8's third placement — "another isolated one" — and the one that must already
        exist: `--workspace` joins and never forks, and this resolves to it."""
        self.as_agent("lead-1")
        self.live("lead-1")
        first = self.spawned("do it", "--worktree", "new", "--name", "a thing")["name"]
        joiner = self.spawned("help out", "--worktree", first, "--name", "some help")
        self.assertEqual(self.row(joiner["name"])["workspace"], first)
        self.assertEqual(joiner["workspace"], first)

    def test_worktree_beside_isolation_or_workspace_is_refused(self):
        """One question, one flag. Two spellings of the same choice in one call is a
        caller that has not decided, and resolving it by precedence is how a child ends up
        somewhere nobody asked for."""
        self.as_agent("lead-1")
        self.live("lead-1")
        for extra in (("--isolation", "own"), ("--workspace", "elsewhere")):
            with self.subTest(extra=extra[0]):
                code, _, err = self.spawn("do it", "--worktree", "same", *extra,
                                          "--name", "a thing")
                self.assertEqual(code, 2)
                self.assertIn(extra[0], err)
                self.assertEqual(self.h.started, [])


if __name__ == "__main__":
    unittest.main()
