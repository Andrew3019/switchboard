"""Role and default-preset layering."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import config, roles  # noqa: E402


class RolesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / ".switchboard").mkdir()
        # Point the global model config at nothing: tier resolution layers ~/.config over
        # the shipped defaults, so without this a developer's own models.toml decides what
        # `cheap` means here and the suite passes or fails per machine.
        env = mock.patch.dict(
            os.environ, {"SWITCHBOARD_MODELS_CONFIG": str(self.repo / "none.toml")})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, toml: str):
        (self.repo / ".switchboard" / "roles.toml").write_text(toml)

    # -- defaults --------------------------------------------------------

    def test_roles_carry_no_preset_config(self):
        """A role is what an agent IS; which presets it gets lives in presets.toml."""
        r = roles.load(self.repo)
        self.assertFalse(hasattr(r["researcher"], "with_"))

    def test_repo_config_overrides_builtin_role_fields(self):
        self.write('[researcher]\nmodel = "strong"\n')
        r = roles.load(self.repo)
        self.assertEqual(r["researcher"].model, "strong")   # builtin default is "cheap"

    # -- what the shipped prompts teach about blocking -------------------

    def test_every_shipped_prompt_that_mentions_blocking_says_where_the_message_goes(self):
        """The misuse this guards: an orchestrator wrote its whole answer to the human into
        a `sb block` reason, which he never reads, and left its own chat empty. `<why>` is
        a clipped field on a board row; the CHAT is what he reads (`sb inspect`).

        Asserted over every shipped prompt rather than the one that was wrong, because the
        original fix was applied to the first file somebody found and three others went on
        teaching the opposite. A prompt is free to never mention blocking; one that does
        must name the chat.
        """
        texts = {"protocol.md": config.protocol(self.repo)}
        for name, role in roles.load(self.repo).items():
            texts[name] = role.prompt
        mentions = {n: t for n, t in texts.items() if "sb block" in t}
        self.assertIn("protocol.md", mentions)         # the one text every agent gets
        for name, t in mentions.items():
            self.assertIn("chat", t, f"{name} names `sb block` but not where the message "
                                     f"goes; the human does not read the reason")

    def test_no_shipped_prompt_tells_an_agent_to_put_the_message_in_the_reason(self):
        """The exact sentence that caused it — "they read that one message ... so say in it
        what you were asked" — read as an instruction to write the message into `<why>`."""
        every = " ".join([config.protocol(self.repo)]
                         + [r.prompt for r in roles.load(self.repo).values()])
        self.assertNotIn("say in it", every)

    # -- what the shipped prompts teach about phase 6's rules -------------
    #
    # Containment checks, and honestly so: they prove the rule is IN the text every agent
    # is sent, not that an agent obeys it. That second thing is not testable here — the
    # only instrument for it is reading what agents actually produce. What these do catch
    # is the failure that has happened repeatedly on this repo: a rule edited into one
    # prompt and silently dropped from the one that ships.

    def test_the_protocol_names_every_sanctioned_reason_to_block(self):
        """DESIGN-TRUTH.md:137-141's five, three of which reached no prompt at all. Each is
        checked by a phrase only that reason would produce, so a rewrite that drops one
        fails here rather than passing on the word "block"."""
        p = config.protocol(self.repo)
        for reason, phrase in {
            "a big design question": "behaviour-changing design question",
            "blocked on running something": "blocked on running",
            "told to block": "told to block",
            "going back and forth": "back and forth",
            "finished work needing approval": "needs Andrew's input or approval",
        }.items():
            with self.subTest(reason=reason):
                self.assertIn(phrase, p)

    def test_the_protocol_states_the_default_shape_of_shipping_work(self):
        """DESIGN-TRUTH.md:344-352, and it goes to every role rather than to orchestrators
        alone — so it is asserted on the protocol, which is the only text all five share."""
        p = config.protocol(self.repo)
        for part in ("branch named for your workspace", "push", "pull request",
                     "URL in your summary"):
            with self.subTest(part=part):
                self.assertIn(part, p)

    def test_no_shipped_prompt_lets_an_agent_merge_unasked(self):
        """DESIGN-TRUTH.md, 2026-08-12: the parent decides, and the parent may be an
        agent. So the prompt must name the parent as the source of the permission, not
        Andrew alone — a brief saying "push" and a prompt saying "never" is the exact
        contradiction four agents each resolved differently."""
        every = " ".join([config.protocol(self.repo)]
                         + [r.prompt for r in roles.load(self.repo).values()])
        self.assertIn("Never merge without that say-so", every)
        self.assertIn("Pushing and merging are your parent's call", every)

    def test_the_protocol_asks_for_skimmable_human_facing_output(self):
        """DESIGN-TRUTH.md's "Human-facing output" rules, 2026-08-14. Skimming is the test
        everything else serves, and the rules say out loud which traffic they govern —
        an unscoped version of them was being applied to `sb tell` and to summaries a
        parent reads."""
        p = config.protocol(self.repo)
        for part in ("skimmed", "bullets", "sections", "only agents read"):
            with self.subTest(part=part):
                self.assertIn(part, p)

    def test_the_human_facing_scope_turns_on_the_reader_not_on_the_verb(self):
        """DESIGN-TRUTH, 2026-08-14: who reads it decides. Keyed on the verb instead, the
        rules exempted the two messages Andrew actually complained about — a session
        write-up answered in the pane, and a top orchestrator's `sb done` summary, whose
        parent is him. The genuine agent-to-agent exemption has to survive that."""
        p = config.protocol(self.repo)
        self.assertIn("Who reads it decides", p)
        self.assertIn("summary when your parent is the human", p)
        self.assertNotIn("summary a parent reads, a task you write for a child", p)
        self.assertIn("`sb tell`", p)               # still exempt: only agents read it

    def test_the_protocol_asks_for_vertical_shape_not_only_for_fewer_words(self):
        """The other half of "too much line wrapping, not enough spacing" — the shipped
        rules named devices (bullets, lists, sections) and never the property they serve.
        A skimming reader moves DOWN the message, so it needs places to stop, and length
        that cannot be cut can still be broken up. "Without overdoing the spacing" pulled
        against that and is gone from every shipped prompt."""
        every = " ".join([config.protocol(self.repo)]
                         + [r.prompt for r in roles.load(self.repo).values()])
        self.assertIn("down the message, not along the line", every)
        self.assertIn("break up", every)
        self.assertNotIn("overdoing the spacing", every)

    def test_no_shipped_prompt_hands_a_human_message_a_list_of_parts(self):
        """What replaced the old ordered checklist ("what you did, then the result, then
        your questions, numbered, each with a recommended answer"): a list of inclusions
        with no rule for leaving something out gets optimised for completion, so the
        protocol asks the cut test instead. Both halves are asserted — the test is
        present, and the checklist has not grown back anywhere."""
        p = config.protocol(self.repo)
        self.assertIn("cutting it would change what they do next", p)
        every = " ".join([p] + [r.prompt for r in roles.load(self.repo).values()])
        for gone in ("recommended answer", "questions numbered", "questions, numbered"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, every)

    def test_the_restatement_instruction_is_taught_exactly_once(self):
        """It was instructed in seven places across the protocol and the role files, which
        is what turned one sentence into a ritual paragraph (DESIGN-TRUTH, 2026-08-14). It
        is unconditional and it survives once; counted over every shipped prompt, because
        the failure is a role file quietly teaching it a second time."""
        texts = [config.protocol(self.repo)]
        texts += [r.prompt for r in roles.load(self.repo).values()]
        self.assertEqual(1, sum(t.count("restating what you were asked") for t in texts))
        self.assertEqual(0, sum(t.count("Restate in one line") for t in texts))

    def test_every_session_is_told_presets_exist_and_can_be_applied(self):
        """"This must be known to all sessions" (DESIGN-TRUTH.md:358-361) — it used to be
        known to orchestrators only, so the protocol is where it has to be."""
        p = config.protocol(self.repo)
        self.assertIn("sb presets", p)
        self.assertIn("--apply", p)

    def test_a_lead_is_told_to_assign_disjoint_files_not_just_to_serialise(self):
        """DESIGN-TRUTH.md:220-221. Serialising overlap was already taught; assigning
        ownership up front — the half that prevents the overlap — was not."""
        prompt = roles.load(self.repo)["orchestrator"].prompt
        self.assertIn("disjoint", prompt)
        self.assertIn("share your worktree", prompt)
        self.assertIn("Serialise", prompt)      # and the half that was already right

    # -- model tiers -----------------------------------------------------

    def test_an_override_replaces_the_roles_tier(self):
        """`sb delegate --model <tier>` picks another tier, not another mechanism."""
        r = roles.load(self.repo)
        spec = roles.get(r, "researcher").spec("strong")     # the role's own tier is cheap
        self.assertEqual(spec.cli_args(), ["--model", "opus", "--effort", "high"])

    def test_a_role_never_hands_out_a_bare_model_id(self):
        """model_id() is gone: it dropped effort, and every caller of it was a bug."""
        self.assertFalse(hasattr(roles.Role("worker"), "model_id"))




if __name__ == "__main__":
    unittest.main()
