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
        """DESIGN-TRUTH: "Agents should avoid blocking unless it is really needed" — its
        five reasons, three of which reached no prompt at all. Each is checked by a
        phrase only that reason would produce, so a rewrite that drops one
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
        """DESIGN-TRUTH: "Pushing and merging are decided by the parent", and it goes to
        every role rather than to orchestrators alone — so it is asserted on the protocol,
        which is the only text all five share."""
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
        """DESIGN-TRUTH.md's "Skimming it is the test." rules, 2026-08-14. Skimming is what
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

    def test_a_message_that_ends_in_a_block_closes_with_where_we_are_now(self):
        """Andrew, 2026-08-16: one line, twenty words, the topic and what stage it is at,
        at the end of the chat message the block is about to leave behind. It is a
        different job from the restatement that opens the message — written as a
        near-duplicate the two collapse into one line — so both halves are pinned."""
        p = config.protocol(self.repo)
        self.assertIn("Where we are now", p)
        self.assertIn("twenty words at most", p)
        self.assertIn("that one says what you were asked, this one says where the work", p)

    def test_the_length_aim_is_stated_and_the_no_mould_line_stops_contradicting_it(self):
        """Andrew, 2026-08-16, choosing a plain aim over the tier scheme he threw out:
        around ten words for a plain fact, about twenty for a tangled one, judged by feel.
        The closing "nothing here is a shape to copy" said "no length to hit" and would
        have read as cancelling it, so that clause is scoped rather than left standing."""
        p = config.protocol(self.repo)
        self.assertIn("a plain fact in ten words or so", p)
        self.assertIn("One idea per bullet", p)
        self.assertIn("Beyond the length aim above", p)
        self.assertNotIn("no length to hit", p)

    def test_the_handoff_is_defined_once_and_the_roles_point_at_it(self):
        """DESIGN-TRUTH, 2026-08-16: a parent may report a child's work once and may not
        become the channel for the conversation about it. The definition lives in the
        protocol, since the rule went missing from `dispatcher` exactly because it lived
        only in `lead.md`; the two role files name it and do not restate the mechanics."""
        p = config.protocol(self.repo)
        self.assertIn("may not become the channel for the conversation about it", p)
        self.assertIn("has this child's finished work already reached the person once?", p)
        roles_by_name = roles.load(self.repo)
        for name in ("dispatcher", "lead"):
            with self.subTest(role=name):
                prompt = roles_by_name[name].prompt
                self.assertIn("handoff the protocol describes", prompt)
                self.assertNotIn("Restore the child if it is closed", prompt)

    def test_every_session_is_told_presets_exist_and_can_be_applied(self):
        """DESIGN-TRUTH: "This must be known to all sessions." It used to be known to
        orchestrators only, so the protocol is where it has to be."""
        p = config.protocol(self.repo)
        self.assertIn("sb presets", p)
        self.assertIn("--apply", p)

    def test_a_dispatcher_asks_before_handing_work_into_another_repo(self):
        """Andrew, on the recruiting incident: a dispatcher may hand work into a different
        repo, but it asks first and it blocks without starting the task. Containment only —
        it proves the rule is in the text every dispatcher is sent, not that one obeys it.
        The failure it guards is the observed one: no flag exists for a cross-repo spawn,
        so a dispatcher that does not stop dispatches a child that forks THIS repo and
        edits the other project through a path."""
        prompt = roles.load(self.repo)["dispatcher"].prompt
        self.assertIn("repo other than the one you were started in", prompt)
        self.assertIn("Do not dispatch it and do not guess", prompt)
        self.assertIn("sb block", prompt)
        self.assertIn("start nothing until you have an answer", prompt)

    def test_a_dispatcher_is_told_setting_up_another_repo_is_not_its_own_job(self):
        """The other half of the same rule, and the half a dispatcher would otherwise get
        wrong by being helpful. Note what is NOT behind it: `sb start` is refused to agents
        (`cli._dispatch`), `sb init` is not — it runs before the caller is even resolved.
        So this sentence is the only thing standing between a helpful dispatcher and a
        pinned repo nobody asked for, which is why it is pinned here."""
        prompt = roles.load(self.repo)["dispatcher"].prompt
        self.assertIn("sb init", prompt)
        self.assertIn("Andrew's to run, not yours", prompt)
        self.assertIn("that tree is not below", prompt)

    def test_a_dispatcher_is_told_flatly_that_it_does_none_of_the_work(self):
        """The prompt is the only mechanism here, and it does not arrive alone: the
        protocol comes first ("do the task you were given"), this repo's house-rules
        preset comes last ("run the suite", "commit on your own branch"), and both are
        written for an agent that works. A trailing "past that you are doing the work" was
        the whole of the counterweight and it loses on position. So the flat statement and
        the tie-break both have to be in the text."""
        prompt = roles.load(self.repo)["dispatcher"].prompt
        self.assertIn("You do none of the work, and that is unconditional", prompt)
        self.assertIn("this file wins", prompt)
        # And the licence that used to undercut it is gone, not merely outweighed.
        self.assertNotIn("a glance at one file", prompt)

    def test_a_dispatcher_is_given_a_verb_for_a_finished_child_and_for_closing_it(self):
        """Two gaps that were both filled by silence. DESIGN-TRUTH says the dispatcher
        blocks when work is done, but the prompt only said what NOT to do with a child's
        report — and a report the dispatcher merely notes to itself reaches nobody, since
        Andrew sees an agent only when it blocks. Cleanup was the mirror image and is now
        the other half of the same block: "not the dispatcher's decision" had been written
        as "not the dispatcher's to touch", which left the one agent that knows a child has
        finished unable to say so usefully. Since 2026-08-15 it closes on his command and
        offers when a child reports fully done — the sweep on its own judgement is what
        stays forbidden, because that is the form that closes something nobody chose.
        Since 2026-08-16 the report verb is scoped to the FIRST time a child reports:
        anything after that is a handoff, and the word is what carries it."""
        prompt = roles.load(self.repo)["dispatcher"].prompt
        self.assertIn("The first time a child reports done", prompt)
        self.assertIn("yours to carry out and never yours to decide", prompt)
        self.assertIn("never do is sweep on your own initiative", prompt)

    def test_a_dispatcher_may_hand_out_a_worker_and_defaults_to_a_lead(self):
        """Andrew, 2026-08-15, replacing lead-every-time: it hands out workers too, on the
        same setup and environment. The guardrail is the half worth pinning — the choice is
        asymmetric (an extra agent against half a job that looks finished), so an unsure
        dispatcher spawns a lead, and nothing here licenses it to size the work by going
        and reading."""
        prompt = roles.load(self.repo)["dispatcher"].prompt
        self.assertIn("--role worker", prompt)
        self.assertIn("Unsure is a lead", prompt)
        self.assertIn("picking who runs the work, never what the work is", prompt)

    def test_a_dispatcher_puts_a_multi_line_ask_in_a_file_rather_than_flattening_it(self):
        """herdr refuses a multi-line agent argument, so "relay it verbatim" and "pass it
        in the task" cannot both hold for anything with structure in it. The reachable move
        was to flatten, which is the lossy rewrite relaying exists to prevent."""
        prompt = roles.load(self.repo)["dispatcher"].prompt
        self.assertIn("-brief.md", prompt)
        self.assertIn("write their words, unaltered", prompt)

    def test_a_lead_is_told_the_dispatcher_role_is_not_one_of_its_options(self):
        """The roles fragment every agent gets is generated from the role table, so it
        advertises `dispatcher` as a name `--role` takes — and it is one: nothing refuses
        it, by the same decision that refuses no other dispatcher behaviour. A nested agent
        given the top's prompt would be told to hold nothing while its children landed as
        tabs, so the role that does the spawning is told not to."""
        prompt = roles.load(self.repo)["lead"].prompt
        self.assertIn("`dispatcher`", prompt)
        self.assertIn("only a human starting one creates it", prompt)

    def test_a_lead_is_told_to_assign_disjoint_files_not_just_to_serialise(self):
        """DESIGN-TRUTH: "so the lead assigns disjoint files and serialises anything".
        Serialising overlap was already taught; assigning ownership up front — the half
        that prevents the overlap — was not."""
        prompt = roles.load(self.repo)["lead"].prompt
        self.assertIn("disjoint", prompt)
        self.assertIn("share your worktree", prompt)
        self.assertIn("Serialise", prompt)      # and the half that was already right

    # -- the dispatcher / lead split --------------------------------------

    def test_both_halves_of_the_split_ship_and_may_delegate(self):
        """One role became two: `dispatcher` at the top, `lead` everywhere nested. Both
        spawn agents, which is the field that matters — a half of the split that cannot
        delegate is a half that cannot do its job."""
        r = roles.load(self.repo)
        for name in ("dispatcher", "lead"):
            with self.subTest(role=name):
                self.assertIn(name, r)
                self.assertTrue(r[name].delegate)
                self.assertTrue(r[name].prompt)

    def test_the_retired_name_resolves_to_the_lead_and_not_to_the_fallback(self):
        """`--role orchestrator` gets typed out of muscle memory long after the rename.
        Unaliased it would inherit `fallback_role` (`worker`), whose `delegate` is False —
        so the one name that used to mean "an agent that splits work" would silently spawn
        an agent that cannot spawn anything. The alias resolves it all the way: the Role
        that comes back IS the lead, name included, so the board, the prompt and the
        stored row agree."""
        r = roles.load(self.repo)
        got = roles.get(r, "orchestrator")
        self.assertEqual(got.name, "lead")
        self.assertTrue(got.delegate)
        self.assertEqual(got.prompt, r["lead"].prompt)

    def test_a_repo_can_write_an_alias_of_its_own(self):
        """The layering that `[vocabulary]` claims and that `roles.get` was not honouring:
        both settings it reads are shipped-then-repo, and it was resolving them with no
        repo at all, so a repo that retired a role of its own and wrote the alias for it got
        silence — the name fell through to the fallback exactly as if nothing was written.
        The shipped alias must survive the repo's, since appending is what every other layer
        in this system does."""
        (self.repo / ".switchboard").mkdir(exist_ok=True)
        (self.repo / ".switchboard" / "settings.toml").write_text(
            "[vocabulary]\nrole_aliases = { foreman = \"lead\" }\n")
        r = roles.load(self.repo)
        self.assertEqual(roles.get(r, "foreman", self.repo).name, "lead")
        self.assertEqual(roles.get(r, "orchestrator", self.repo).name, "lead")

    def test_a_dispatcher_and_a_lead_are_given_different_jobs(self):
        """The one thing that justifies two prompts rather than one with a branch in it: a
        dispatcher is built to hold nothing and a lead to hold everything about its task.
        Asserted on the sentence each one opens with, so a merge that quietly re-unified
        the two texts fails here."""
        r = roles.load(self.repo)
        self.assertIn("hold no task", r["dispatcher"].prompt)
        self.assertNotIn("hold no task", r["lead"].prompt)
        self.assertIn("own one task from end to end", r["lead"].prompt)

    # -- model tiers -----------------------------------------------------

    def test_every_shipped_role_pins_the_tier_the_table_chose(self):
        """The table in `notes/model-selection.md`, in the form the spawn layer sees it.

        Four roles, not six: `reviewer` and `worker` were moved off `default` by that pass
        and Andrew moved them back the same day, so they are deliberately absent here rather
        than asserted to be empty — the tier a role does NOT pin is that role file's
        statement to make, and reviewer.md and worker.md make it.

        Pinned as a DECISION, not as behaviour.
        """
        r = roles.load(self.repo)
        want = {
            "dispatcher": ["--model", "sonnet", "--effort", "medium"],
            "researcher": ["--model", "sonnet", "--effort", "medium"],
            "qa":         ["--model", "sonnet", "--effort", "high"],
            "lead":       ["--model", "claude-opus-4-8", "--effort", "high"],
        }
        got = {name: roles.get(r, name).spec().cli_args() for name in want}
        self.assertEqual(got, want)

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
