"""E1 — the guidance ledger: rules delivered at the turn they apply to (spec §2.4).

Four things a test can pin here, and they are the four the unit is:

* **matching** — a rule fires on the state it names and stays silent on every other, with
  conditions that are store facts rather than judgements;
* **precedence** — live-state before command before role before global, ties by the order
  the ledger is written in;
* **the cursor** — `every-time` / `once` / `once-until-clear`, which is the
  per-`(agent, rule)` state that generalizes `hooks._already_nudged`;
* **the subtractive win** — the `sb merge` paragraph is GONE from the spawn prompt and
  arrives through the ledger instead.

What a test cannot pin is that Claude Code injects the hook's stdout into the agent's
context. That half is the shipped `UserPromptSubmit` channel, already relied on by nothing
until now, and it is proved live in an isolated clone rather than here.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import config, guidance, hooks, store  # noqa: E402


def rule(**kw) -> guidance.Rule:
    """One rule, straight from its authored form — the same path the TOML takes."""
    return guidance._rule(kw, kw.pop("_order", 0))


class Fixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.db = store.connect(path=self.repo / "state.db")

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def agent(self, name, role="worker", **kw):
        store.create_agent(self.db, name=name, role=role, **kw)
        return name

    def ledger_file(self, body: str) -> None:
        """This repo's own layer, the way a person would edit it."""
        d = self.repo / ".switchboard"
        d.mkdir(exist_ok=True)
        (d / "guidance.toml").write_text(body)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


class MatchTest(Fixture, unittest.TestCase):
    def test_a_rule_fires_on_the_state_it_names_and_not_on_any_other(self):
        """The whole mechanism in one assertion pair: role, command and live state agree,
        or nothing is said. The condition is a COUNT out of the store — there is no fuzzy
        predicate to get right, which is the property being pinned as much as the match."""
        r = rule(id="r", text="fold it in", role="lead", command="delegate",
                 when=[{"fact": "finished_children", "op": ">=", "value": 1}])
        self.agent("lead-x", role="lead")
        self.agent("w1", parent="lead-x")

        # Right role, right command, wrong state — the child is still working.
        self.assertEqual(guidance.resolve(self.db, "lead-x", command="delegate",
                                          rules=[r]), [])
        store.set_state(self.db, "w1", "done")
        self.assertEqual(guidance.resolve(self.db, "lead-x", command="delegate",
                                          rules=[r]), [r])
        # Right state, wrong command.
        self.assertEqual(guidance.resolve(self.db, "lead-x", rules=[r]), [])
        # Right state and command, wrong role.
        self.agent("other-lead", role="worker")
        store.create_agent(self.db, name="w2", role="worker", parent="other-lead")
        store.set_state(self.db, "w2", "done")
        self.assertEqual(guidance.resolve(self.db, "other-lead", command="delegate",
                                          rules=[r]), [])

    def test_rules_match_the_live_capability_set_not_the_role_template(self):
        """Obj. 7. A rule that told a worker to ask its lead to spawn must stop the moment
        that lead granted it `spawn` — matching the template instead is exactly how a
        nudge outlives the thing it was nudging about."""
        r = rule(id="ask-first", text="ask your lead", lacks=["spawn"])
        self.agent("w1")
        store.seed_capabilities(self.db, "w1", [])
        self.assertEqual(guidance.resolve(self.db, "w1", rules=[r]), [r])

        store.grant_capability(self.db, "w1", "spawn", delegable=False,
                               granted_by="lead-x")
        self.assertEqual(guidance.resolve(self.db, "w1", rules=[r]), [])

    def test_a_condition_may_only_name_a_fact_the_store_can_answer(self):
        """The guard that keeps conditions deterministic. A rule asking something the
        store has no answer for is a config error at load — never a rule that quietly
        never fires, which is the failure nobody would ever notice."""
        with self.assertRaises(config.ConfigError) as cm:
            rule(id="bad", text="x",
                 when=[{"fact": "is_this_non_trivial", "op": "==", "value": True}])
        self.assertIn("no such fact", str(cm.exception))
        with self.assertRaises(config.ConfigError):
            rule(id="bad", text="x", when=[{"fact": "children", "op": "~", "value": 1}])
        with self.assertRaises(config.ConfigError):
            rule(id="bad", text="x", repeat="sometimes")


class PrecedenceTest(Fixture, unittest.TestCase):
    def test_most_specific_first_and_ties_keep_ledger_order(self):
        """Obj. 6, one assertion per level plus the tie. Precedence decides the ORDER —
        every matching rule is still delivered, because a rule that matched and was
        silently outranked is one nobody could reason about from the ledger."""
        rules = [
            rule(id="g", text="global", _order=0),
            rule(id="r", text="role", role="lead", _order=1),
            rule(id="c", text="command", command="delegate", _order=2),
            rule(id="s", text="state", when=[{"fact": "children", "op": ">=", "value": 1}],
                 _order=3),
            rule(id="s2", text="state too", when=[{"fact": "children", "op": ">=", "value": 0}],
                 _order=4),
        ]
        self.agent("lead-x", role="lead")
        self.agent("w1", parent="lead-x")
        got = [x.id for x in guidance.resolve(self.db, "lead-x", command="delegate",
                                              rules=rules)]
        self.assertEqual(got, ["s", "s2", "c", "r", "g"])


# ---------------------------------------------------------------------------
# The repeat-policy cursor
# ---------------------------------------------------------------------------


class RepeatTest(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.agent("w1")
        self.always = [{"fact": "children", "op": ">=", "value": 0}]

    def fire(self, r):
        return guidance.deliver(self.db, "w1", rules=[r])

    def test_every_time_says_it_every_time(self):
        r = rule(id="e", text="remember", repeat="every-time", when=self.always)
        self.assertIn("remember", self.fire(r))
        self.assertIn("remember", self.fire(r))

    def test_once_says_it_once_per_agent_and_never_again(self):
        """The cursor outlives the stop-chain, the pane and the session — which is the
        thing `_already_nudged` had to approximate by reading the event log."""
        r = rule(id="o", text="remember", repeat="once", when=self.always)
        self.assertIn("remember", self.fire(r))
        self.assertEqual(self.fire(r), "")
        self.assertEqual(self.fire(r), "")
        self.assertEqual(
            store.guidance_cursors(self.db, "w1")["o"]["deliveries"], 1)

    def test_once_until_clear_re_arms_when_the_state_goes_away(self):
        """Said when the situation arrives, silent while it lasts, said again when it
        comes back. The clear is written by the same pass, on the turn the condition stops
        holding — nothing else ever looks at it."""
        r = rule(id="u", text="remember", repeat="once-until-clear",
                 when=[{"fact": "finished_children", "op": ">=", "value": 1}])
        store.create_agent(self.db, name="c1", role="worker", parent="w1")

        self.assertEqual(self.fire(r), "")                     # not yet
        store.set_state(self.db, "c1", "done")
        self.assertIn("remember", self.fire(r))                # arrived
        self.assertEqual(self.fire(r), "")                     # still true, still quiet
        store.set_state(self.db, "c1", "working")
        self.assertEqual(self.fire(r), "")                     # gone: cleared, not said
        self.assertIsNotNone(store.guidance_cursors(self.db, "w1")["u"]["cleared_at"])
        store.set_state(self.db, "c1", "done")
        self.assertIn("remember", self.fire(r))                # back: said again
        self.assertEqual(store.guidance_cursors(self.db, "w1")["u"]["deliveries"], 2)

    def test_a_suppressed_rule_does_not_refresh_its_own_cursor(self):
        """The bug this could most easily have shipped: recording a delivery for a rule
        that was suppressed leaves `once-until-clear` never clearing."""
        r = rule(id="u", text="remember", repeat="once-until-clear", when=self.always)
        self.fire(r)
        first = store.guidance_cursors(self.db, "w1")["u"]["delivered_at"]
        self.fire(r)
        self.assertEqual(store.guidance_cursors(self.db, "w1")["u"]["delivered_at"], first)
        self.assertEqual(store.guidance_cursors(self.db, "w1")["u"]["deliveries"], 1)

    def test_the_cursor_is_per_agent_and_per_rule(self):
        """Both halves of the key. One agent being told something says nothing about
        another, and a name that comes back reusable must not inherit a delivered mark."""
        r = rule(id="o", text="remember", repeat="once", when=self.always)
        self.agent("w2")
        self.assertIn("remember", guidance.deliver(self.db, "w1", rules=[r]))
        self.assertIn("remember", guidance.deliver(self.db, "w2", rules=[r]))
        store.drop_agent(self.db, "w1")
        self.assertEqual(store.guidance_cursors(self.db, "w1"), {})


# ---------------------------------------------------------------------------
# The channel
# ---------------------------------------------------------------------------


class ChannelTest(Fixture, unittest.TestCase):
    """`hooks.run_activity` — the shipped `UserPromptSubmit` hook, unchanged in shape."""

    def payload(self):
        return json.dumps({"session_id": "sess-1"})

    def test_the_hook_says_nothing_when_no_rule_fires(self):
        """Obj. 3 — zero added context, zero regression. The turn edge is still written,
        which is the other half of the same call."""
        self.agent("w1", session_id="sess-1")
        said = hooks.run_activity(self.payload(), db_path=self.repo / "state.db")
        self.assertEqual(said, "")
        self.assertEqual(store.get_agent(self.db, "w1")["turn"], store.TURN_WORKING)

    def test_a_matching_rule_is_returned_marked_and_the_turn_edge_still_lands(self):
        """The delivery, over the real entry point's arguments. The mark is what stops an
        injected rule from reading as the human typing."""
        self.agent("lead-x", role="lead", session_id="sess-1", branch="lead-x")
        store.create_agent(self.db, name="c1", role="worker", parent="lead-x", branch="c1")
        store.set_state(self.db, "c1", "done")
        said = hooks.run_activity(self.payload(), db_path=self.repo / "state.db")
        self.assertIn(guidance.MARK, said)
        self.assertIn("sb merge", said)
        self.assertEqual(store.get_agent(self.db, "lead-x")["turn"], store.TURN_WORKING)

    def test_a_broken_ledger_costs_silence_not_the_turn_edge(self):
        """Fails open, like everything else in `hooks`. A ledger that will not parse must
        not stop an agent's turns being recorded."""
        self.agent("w1", session_id="sess-1")
        self.ledger_file("this is not toml [[[")
        said = hooks.run_activity(self.payload(), db_path=self.repo / "state.db")
        self.assertEqual(said, "")
        self.assertEqual(store.get_agent(self.db, "w1")["turn"], store.TURN_WORKING)


# ---------------------------------------------------------------------------
# The ledger as data
# ---------------------------------------------------------------------------


class LedgerTest(Fixture, unittest.TestCase):
    def test_a_repo_adds_rules_and_the_shipped_ones_survive(self):
        self.ledger_file(
            '[[rule]]\nid = "mine"\ntext = "house rule"\nrole = "worker"\n')
        ids = [r.id for r in guidance.ledger(self.repo)]
        self.assertIn("mine", ids)
        self.assertIn("merge-finished-isolated-child", ids)

    def test_an_edit_reaches_an_agent_that_is_already_running(self):
        """Obj. 10, and the reason the ledger is a FILE rather than a constant: the rules
        are read afresh on every turn, so editing them lands on the next turn of every
        agent already up — no restart, no respawn, no new spawn prompt."""
        self.agent("w1")
        self.ledger_file('[[rule]]\nid = "mine"\ntext = "first wording"\n'
                         'role = "worker"\nrepeat = "every-time"\n')
        self.assertIn("first wording", guidance.deliver(self.db, "w1", repo=self.repo))

        self.ledger_file('[[rule]]\nid = "mine"\ntext = "second wording"\n'
                         'role = "worker"\nrepeat = "every-time"\n')
        said = guidance.deliver(self.db, "w1", repo=self.repo)
        self.assertIn("second wording", said)
        self.assertNotIn("first wording", said)

    def test_the_shipped_worktree_rule_carries_the_threshold_it_is_written_against(self):
        """The one number this file duplicates. D4 left `WORKTREE_SOFT_THRESHOLD` with
        nothing behind it and named a ledger rule as the consumer; this is that rule, and
        this assertion is what stops the two drifting apart quietly."""
        from switchboard import status
        r = next(r for r in guidance.ledger() if r.id == "worktree-fan-out")
        self.assertEqual(
            [c for c in r.when if c[0] == "worktrees"][0][2],
            status.WORKTREE_SOFT_THRESHOLD)


class PolicyMechanismTest(Fixture, unittest.TestCase):
    """Obj. 15 — the convention became soft guidance; the wall stayed a capability."""

    def test_the_delegate_convention_is_a_command_rule_and_fires_on_no_turn(self):
        """It is keyed on the command, because "who should I hand this to" is a question
        that only exists while delegating — there is no standing state at turn start that
        means it. The half pinned here is the SILENCE at turn start; that it now fires
        under `sb delegate` is E2's call site (`cli._state_output`, `test_state_output`)."""
        self.agent("lead-x", role="lead")
        store.seed_capabilities(self.db, "lead-x", ["spawn"])
        ids = lambda **kw: [r.id for r in guidance.resolve(self.db, "lead-x", **kw)]  # noqa: E731
        self.assertNotIn("delegate-to-a-lead", ids())
        self.assertIn("delegate-to-a-lead", ids(command="delegate"))

    def test_an_agent_that_cannot_spawn_is_never_told_who_to_delegate_to(self):
        self.agent("w1")
        store.seed_capabilities(self.db, "w1", [])
        self.assertNotIn("delegate-to-a-lead",
                         [r.id for r in guidance.resolve(self.db, "w1", command="delegate")])


class DiscoverabilityTest(Fixture, unittest.TestCase):
    """The two verbs that shipped without ever being said to an agent: `sb delegate
    --isolation own` and `sb done --preserve-children`. Both are taught here rather than in
    the spawn prompt, so what a test can pin is that each fires on its own condition and on
    nothing else — the ledger's whole claim being that a rule costs only the agent the state
    describes."""

    def test_isolation_is_offered_at_the_spawn_and_only_to_an_agent_that_may_fork(self):
        """Keyed on the command, because the choice exists while delegating and at no other
        turn — so the silence at turn start is half the rule. `holds = ["fork"]` is the
        other half: an agent whose `--isolation own` would be refused is never told it."""
        self.agent("lead-x", role="lead")
        store.seed_capabilities(self.db, "lead-x", ["spawn", "fork"])
        ids = lambda who, **kw: [r.id for r in guidance.resolve(self.db, who, **kw)]  # noqa: E731
        self.assertNotIn("isolation-at-the-spawn", ids("lead-x"))
        self.assertIn("isolation-at-the-spawn", ids("lead-x", command="delegate"))

        self.agent("w1")
        store.seed_capabilities(self.db, "w1", ["spawn"])
        self.assertNotIn("isolation-at-the-spawn", ids("w1", command="delegate"))

    def test_the_direct_path_tier_is_offered_at_the_spawn_and_only_to_a_spawner(self):
        """`gpt-luna-max-effort` is chosen at a spawn or never — the model is written
        before the child's shell launches and `restore` reuses the stored tier — so the
        one moment this can be acted on is `sb delegate`, and an agent that cannot spawn
        is never told about a tier it has no way to name."""
        self.agent("lead-x", role="lead")
        store.seed_capabilities(self.db, "lead-x", ["spawn"])
        ids = lambda who, **kw: [r.id for r in guidance.resolve(self.db, who, **kw)]  # noqa: E731
        self.assertNotIn("direct-path-tier-at-the-spawn", ids("lead-x"))
        self.assertIn("direct-path-tier-at-the-spawn", ids("lead-x", command="delegate"))

        self.agent("r1", role="researcher")
        store.seed_capabilities(self.db, "r1", [])
        self.assertNotIn("direct-path-tier-at-the-spawn", ids("r1", command="delegate"))

    def test_the_direct_path_tier_is_said_at_every_delegate_and_not_just_the_first(self):
        """`every-time`, against the ledger's own default, and the decision worth pinning:
        a dispatcher makes this choice once per issue it hands out, so a rule that fired
        on its first-ever delegate and never again would be the weak version of it. The
        rows keyed on the same verb beside it are `once`; this one is deliberately not."""
        self.agent("d1", role="dispatcher")
        store.seed_capabilities(self.db, "d1", ["spawn"])
        said = lambda: guidance.deliver(self.db, "d1", command="delegate", repo=self.repo)  # noqa: E731
        first, second = said(), said()
        self.assertIn("gpt-luna-max-effort", first)
        self.assertIn("gpt-luna-max-effort", second)
        # The `once` row keyed on the same verb, for contrast: said on the first delegate
        # of this agent's life and never again.
        self.assertIn("WHO OWNS IT", first)
        self.assertNotIn("WHO OWNS IT", second)

    def test_a_command_keyed_rule_names_a_verb_that_actually_carries_the_key(self):
        """The failure mode the ledger header warns about: a rule keyed on a verb outside
        `cli.STATE_COMMANDS` never fires, and nobody notices because a nudge that is never
        delivered looks exactly like a nudge nobody needed. This is why the promote rule
        below turns on live state instead — `done` is not one of these."""
        from switchboard import cli
        for r in guidance.ledger():
            if r.command:
                self.assertIn(r.command, cli.STATE_COMMANDS, r.id)
        self.assertNotIn("done", cli.STATE_COMMANDS)

    def test_promote_is_taught_while_children_are_still_live_and_not_after(self):
        """`live_children >= 1` is the state the hand-off is about: finish now and they are
        left under an agent that has finished. An agent with no children, or whose children
        have all reported, has nothing to hand up and hears nothing."""
        ids = lambda who: [r.id for r in guidance.resolve(self.db, who)]  # noqa: E731
        self.agent("lead-x", role="lead", branch="lead-x")
        self.assertNotIn("hand-children-up-when-you-step-out", ids("lead-x"))

        store.create_agent(self.db, name="c1", role="worker", parent="lead-x",
                           branch="lead-x")
        self.assertIn("hand-children-up-when-you-step-out", ids("lead-x"))

        store.set_state(self.db, "c1", "done")
        self.assertNotIn("hand-children-up-when-you-step-out", ids("lead-x"))


class SubtractiveTest(Fixture, unittest.TestCase):
    """Obj. 11 — the prompt SHRANK. Moved, not copied, and not merely added."""

    def test_the_merge_rule_left_the_spawn_prompt_and_arrives_from_the_ledger(self):
        self.assertNotIn("sb merge", config.protocol(self.repo))
        r = next(r for r in guidance.ledger() if r.id == "merge-finished-isolated-child")
        self.assertIn("sb merge", r.text)

        self.agent("lead-x", role="lead", branch="lead-x")
        store.create_agent(self.db, name="c1", role="worker", parent="lead-x", branch="c1")
        store.set_state(self.db, "c1", "done")
        self.assertIn("sb merge", guidance.deliver(self.db, "lead-x", repo=self.repo))

    def test_a_shared_child_is_not_something_to_merge(self):
        """`mergeable_children` counts what `sb merge` would accept and nothing else: a
        `shared` child's work is already on the caller's branch, and nudging a lead to
        merge it would be a nudge toward a refusal."""
        self.agent("lead-x", role="lead", branch="lead-x")
        store.create_agent(self.db, name="c1", role="worker", parent="lead-x",
                           branch="lead-x")
        store.set_state(self.db, "c1", "done")
        self.assertEqual(guidance.deliver(self.db, "lead-x", repo=self.repo), "")

    def test_what_must_be_true_from_turn_one_stayed_in_the_prompt(self):
        """Obj. 12 — the win is partial and claimed only for reminder-shaped rules.
        Identity and orientation prose has no later turn to wait for."""
        p = config.protocol(self.repo)
        for kept in ("sb done", "sb block", "sb delegate", "sb inbox"):
            self.assertIn(kept, p)


if __name__ == "__main__":
    unittest.main()
