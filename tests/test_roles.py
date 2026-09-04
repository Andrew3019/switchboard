"""Role and default-preset layering."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import config, models, roles  # noqa: E402


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
        """DESIGN-TRUTH: "Pushing and PR landing follow the change record's authority", and it goes to
        every role rather than to orchestrators alone — so it is asserted on the protocol,
        which is the only text all five share."""
        p = config.protocol(self.repo)
        for part in ("branch named for your workspace", "push", "pull request",
                     "URL in your summary"):
            with self.subTest(part=part):
                self.assertIn(part, p)

    def test_the_protocol_keeps_upward_messages_to_actionable_needs(self):
        """Every role gets the same rule: routine progress belongs in the agent's own
        work, and upward messages are reserved for a parent that must act."""
        p = " ".join(config.protocol(self.repo).split())
        for phrase in (
            "Do not narrate your progress to your parent",
            "learns what you did from your `sb done` summary",
            "Message your parent before you finish only when it must act",
            "A progress FYI that asks nothing of the reader is noise",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, p)

    def test_no_shipped_prompt_forbids_merging(self):
        """PLANS-AND-STEPS, 2026-08-16: the plans plugin's merge gate tells an agent to
        merge, so the prohibition is cut back to a pointer at it — a gate saying merge and
        a prompt saying never is the same contradiction four agents each resolved
        differently, and the cut has to land before the gate ships. What replaces it names
        who decides in both cases: the gate under a plan, the parent without one."""
        every = " ".join([config.protocol(self.repo)]
                         + [r.prompt for r in roles.load(self.repo).values()])
        self.assertNotIn("ever merge without", every)        # "Never"/"never merge without"
        self.assertIn("its merge gate is the authority on landing", every)
        self.assertIn("where none is, your parent's instruction is", every)

    def test_the_merge_gate_gates_the_merge_not_the_push_or_pr(self):
        """2026-09-01: a sole worker committed a fix and stopped, reading "its merge gate is
        the authority on pushing AND merging" as leaving push/PR to a parent. DESIGN-TRUTH:
        "The task owner may push and open the PR after implementation, applicable
        verification and fresh review are complete." has said the
        gate covers only the merge since 2026-08-27, so the protocol is reconciled to it: the
        owner pushes and opens the PR itself after review, a sole agent with no parent
        included, and only the merge is gated."""
        p = config.protocol(self.repo)
        # the gate is scoped to the merge, not the push or the PR
        self.assertIn("What is gated is the MERGE, not the push or the PR", p)
        self.assertNotIn("authority on pushing and merging", p)
        # a sole agent with no parent still pushes and opens its own PR
        self.assertIn("a sole owner still pushes and opens its own PR", p)

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

    def test_a_dispatcher_closes_without_asking_when_the_merge_was_andrews(self):
        """Andrew, 2026-08-29: the close-confirm is redundant after a merge he decided —
        the merge is the acceptance, and being asked to accept the same work twice is the
        noise this removes. The exception is drawn on WHO DECIDED the merge, not on the
        merge itself, because standing authorisation lets an agent land work he has never
        looked at and this question is where that surfaces. So both halves are pinned: the
        close on his merge, and the ask that survives for an agent's own."""
        prompt = roles.load(self.repo)["dispatcher"].prompt
        self.assertIn("work that landed on a merge THEY decided", prompt)
        self.assertIn("close it with `sb cleanup <name>`", prompt)
        self.assertIn("decided on its own standing authority is not that", prompt)
        # The report is still owed; only the question goes.
        self.assertIn("The first time a child reports done", prompt)

    def test_a_dispatcher_may_hand_out_a_worker_and_defaults_to_a_lead(self):
        """Andrew, 2026-08-15, replacing lead-every-time: it hands out workers too, on the
        same setup and environment. The guardrail is the half worth pinning — the choice is
        asymmetric (an extra agent against half a job that looks finished), so an unsure
        dispatcher spawns a lead, and nothing here licenses it to size the work by going
        and reading.

        Two more since 2026-08-27. `researcher` joined the routing options for the ask that
        is explicitly to look and report; and choosing a lead is pinned as committing nobody
        to delegating anything, because that is the sentence a lead prompt no longer
        promising a fan-out needs the dispatcher to agree with."""
        prompt = roles.load(self.repo)["dispatcher"].prompt
        self.assertIn("--role worker", prompt)
        self.assertIn("--role researcher", prompt)
        self.assertIn("Unsure is a lead", prompt)
        self.assertIn("Choosing a lead commits nobody to delegating anything", prompt)
        self.assertIn("picking who owns the work, never what the work is", prompt)

    def test_a_dispatcher_puts_a_multi_line_ask_in_a_file_rather_than_flattening_it(self):
        """herdr refuses a multi-line agent argument, so "relay it verbatim" and "pass it
        in the task" cannot both hold for anything with structure in it. The reachable move
        was to flatten, which is the lossy rewrite relaying exists to prevent.

        This pins the file/flatten decision only. WHERE the file goes changed on
        2026-08-16 and is pinned separately below, because this assertion was loose
        enough that the old `notes/` location could have drifted back unnoticed."""
        prompt = roles.load(self.repo)["dispatcher"].prompt
        self.assertIn("brief.md", prompt)
        self.assertIn("write their words, unaltered", prompt)

    def test_a_brief_goes_under_gitignored_switchboard_and_never_under_notes(self):
        """Andrew, 2026-08-16. `notes/` is tracked, so ~48 briefs in two weeks were
        committed to main as a side effect of relaying. `.switchboard/` is gitignored and
        `link_config` symlinks it into every worktree, so one absolute path both stays off
        main and reads the same from the child's tree. Nothing at the tool layer enforces
        this — the prompt is the whole mechanism, so the prompt is what gets asserted."""
        prompt = roles.load(self.repo)["dispatcher"].prompt
        self.assertIn(".switchboard/briefs/", prompt)
        self.assertNotIn("notes/", prompt)

    def test_a_lead_is_given_the_same_place_to_put_a_brief_as_a_dispatcher(self):
        """The location was pinned for `dispatcher` and nowhere else, but a lead spawns
        children too and hits the same newline refusal — so for a lead the path was pure
        habit, and the habit was the tracked `notes/` that put ~48 briefs on main. Same
        rule, stated for the other role that delegates; the prompt is again the whole
        mechanism, so the prompt is what gets asserted.

        The "not notes/" half is scoped to the sentence that says where a brief goes,
        rather than to the whole prompt: since 2026-08-19 the lead is also told what may be
        committed to the tracked `notes/` tree, which is a different rule about the same
        directory and would otherwise have to be worded around this assertion."""
        prompt = roles.load(self.repo)["lead"].prompt
        self.assertIn(".switchboard/briefs/", prompt)
        self.assertIn("brief.md", prompt)
        brief = next(s for s in prompt.split(". ") if "brief.md" in s)
        self.assertNotIn("notes/", brief)

    def test_findings_go_under_gitignored_switchboard_notes_in_all_three_reporting_roles(self):
        """Andrew, 2026-08-19. The tracked `notes/` tree had 148 files and 6 of them were
        ever referenced again, so an ordinary research, qa or review task left a permanent
        file on main that nobody read. Findings now go where briefs already go: gitignored,
        and symlinked into every worktree so the parent still reads the same path. The
        prompt is the whole mechanism, as with briefs, so the prompt is what gets asserted
        — and the sentence is shared verbatim across the three roles on purpose."""
        r = roles.load(self.repo)
        shared = ("`.switchboard/notes/<your agent name>-<topic>.md` under\n"
                  "the root of the checkout you are working in, creating "
                  "`.switchboard/notes/` if it is not\nthere")
        for name in ("researcher", "qa", "reviewer"):
            with self.subTest(role=name):
                self.assertIn(" ".join(shared.split()), " ".join(r[name].prompt.split()))

    def test_a_lead_and_a_reviewer_are_told_tracked_notes_is_entered_by_promotion(self):
        """The move above fixes the child's end; the lead and the reviewer are who COMMIT,
        and a standalone tracked file per finished investigation is how the 148 accrued. So
        both are told the tracked tree is entered deliberately — folded into a doc that is
        already maintained, or cited by code or a test — and never as the default outcome
        of a research, qa or review task."""
        r = roles.load(self.repo)
        for name in ("lead", "reviewer"):
            with self.subTest(role=name):
                prompt = " ".join(r[name].prompt.split())
                self.assertIn("is a promotion", prompt)
                self.assertIn("tracked `notes/` tree", prompt)

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
        """DESIGN-TRUTH: "Shared placement does not determine decomposition".
        Serialising overlap was already taught; assigning ownership up front — the half
        that prevents the overlap — was not."""
        prompt = roles.load(self.repo)["lead"].prompt
        self.assertIn("disjoint", prompt)
        self.assertIn("share your worktree", prompt)
        self.assertIn("Serialise", prompt)      # and the half that was already right

    # -- the dispatcher / lead split --------------------------------------

    def test_both_halves_of_the_split_ship_and_may_delegate(self):
        """One role became two: `dispatcher` at the top, `lead` everywhere nested. Both
        spawn agents, which is what matters — a half of the split that cannot delegate is a
        half that cannot do its job.

        Asked of the capability bundle since C1 retired `delegate: bool`. Same question,
        same answer: "may this role spawn" is `spawn` in its default set."""
        r = roles.load(self.repo)
        for name in ("dispatcher", "lead"):
            with self.subTest(role=name):
                self.assertIn(name, r)
                self.assertIn(roles.CAP_SPAWN, r[name].capabilities)
                self.assertTrue(r[name].prompt)

    def test_the_retired_name_resolves_to_the_lead_and_not_to_the_fallback(self):
        """`--role orchestrator` gets typed out of muscle memory long after the rename.
        Unaliased it would inherit `fallback_role` (`worker`), which holds no `spawn` —
        so the one name that used to mean "an agent that splits work" would silently spawn
        an agent that cannot spawn anything. The alias resolves it all the way: the Role
        that comes back IS the lead, name included, so the board, the prompt and the
        stored row agree."""
        r = roles.load(self.repo)
        got = roles.get(r, "orchestrator")
        self.assertEqual(got.name, "lead")
        self.assertIn(roles.CAP_SPAWN, got.capabilities)
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

    def test_an_unknown_role_is_refused_and_points_at_the_live_vocabulary(self):
        """Phase 1: an undefined `--role` used to be a role. It inherited the fallback's
        model, prompt and capabilities but kept the typed name, so `--role wroker` spawned
        a worker-shaped agent filed under a name nobody defined and nothing said so. A
        misspelling is now a refusal that names the near misses and the command that lists
        them — the escape hatch for a genuinely custom disposition is `--as`, which is
        explicit and still takes a configured role's profile."""
        r = roles.load(self.repo)
        with self.assertRaises(roles.RoleConfigError) as cm:
            roles.get(r, "wroker", self.repo)
        said = str(cm.exception)
        self.assertIn("no role 'wroker'", said)
        self.assertIn("worker", said)
        self.assertIn("sb roles", said)
        self.assertIn("--as", said)

    def test_a_normalized_role_collision_asks_for_an_exact_name(self):
        """Case and punctuation variants resolve only where they identify ONE role. A repo
        that adds a name normalizing onto a shipped one has two live answers, and guessing
        between them is how a spawn silently gets the other one's capabilities."""
        self.write('[re_viewer]\nmodel = "cheap"\nprompt = "mine"\n')
        r = roles.load(self.repo)
        self.assertEqual(roles.get(r, "re_viewer", self.repo).name, "re_viewer")  # exact
        with self.assertRaises(roles.RoleConfigError) as cm:
            roles.get(r, "Re Viewer", self.repo)
        said = str(cm.exception)
        self.assertIn("ambiguous", said)
        self.assertIn("re_viewer", said)
        self.assertIn("reviewer", said)

    def test_a_role_already_in_the_store_stays_readable_after_the_refusal(self):
        """The compatibility half of the same change. Strictness is for what a caller
        TYPES; a row already written under an ad-hoc role predates it, and refusing that
        name at read time would make the agent unrestorable and its stored model
        unresolvable. `get_or_fallback` is that reader and nothing else uses it."""
        r = roles.load(self.repo)
        got = roles.get_or_fallback(r, "archaeologist", self.repo)
        self.assertEqual(got.name, "archaeologist")
        self.assertEqual(got.capabilities, r["worker"].capabilities)
        self.assertEqual(got.prompt, r["worker"].prompt)

    def test_no_shipped_prompt_tells_a_task_owner_to_delegate_by_default(self):
        """2026-08-27, and the largest of the workflow-repair prompt changes. DESIGN-TRUTH:
        "A lead owns the requested outcome and may perform every ordinary part of it. It may
        investigate, read and edit the codebase, design, implement, verify, integrate,
        communicate with Andrew and land the work within its authority."

        The lead prompt used to say the opposite four times over, and the observed effect
        was a lead spawning a lead to do its own job. Pinned as an absence across every
        delivered prompt AND the guidance ledger, because the sentences were spread over a
        role file and a reminder that fires at the moment of spawning — a rewrite of one
        that left the other would restore the contradiction with nothing failing."""
        every = " ".join([config.protocol(self.repo)]
                         + [r.prompt for r in roles.load(self.repo).values()])
        lead = roles.load(self.repo)["lead"].prompt
        for retired in ("get other agents to do the work rather than doing it yourself",
                        "Do not do the work yourself",
                        "Do not read the codebase yourself",
                        "delegate real work"):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, every)
        # And the positive half, so the absence cannot be satisfied by saying nothing.
        self.assertIn("Owning it means doing it", lead)
        self.assertIn("That is authority, not an instruction", lead)
        # The one delegation nothing may make optional.
        self.assertIn("reviewed by a fresh agent that did not write it", lead)

    def test_a_worker_gates_done_on_the_fresh_review(self):
        prompt = " ".join(roles.load(self.repo)["worker"].prompt.split())
        self.assertIn("reviewed by a fresh agent that did not write it", prompt)
        self.assertIn("before you call `sb done`", prompt)

    def test_a_lead_keeps_routine_upward_messages_in_its_subtree(self):
        prompt = " ".join(roles.load(self.repo)["lead"].prompt.split())
        for phrase in (
            "universal rule against progress narration governs what you send upward",
            "Routine fan-out arrivals",
            "merge-order coordination you resolved with your own children",
            "final `sb done` rather than sending them one at a time",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)
        self.assertNotIn("Message your parent only when something is parent-actionable", prompt)

    def test_the_protocol_forbids_quietly_doing_less_than_was_asked(self):
        """The other direction of scope, and the one that was ungoverned: "do only what you
        were asked" was read as the whole rule, so deferring a phase, dropping a contract
        item or re-reading an exit condition as optional was a call any agent could make and
        report as a finished job. It is universal, so it is the protocol's — and the
        reviewer is the reader that has to act on it, so it is pinned in both places."""
        p = config.protocol(self.repo)
        self.assertIn("Doing LESS than you were asked", p)
        self.assertIn("propose it", p)
        self.assertIn("recorded change to the contract", p)
        reviewer = roles.load(self.repo)["reviewer"].prompt
        self.assertIn("treat anything unmet as unresolved", reviewer)

    def test_a_reviewer_may_apply_a_minor_fix_and_is_told_what_that_reaches(self):
        """DESIGN-TRUTH: "A safe local unambiguous minor fix is applied by the reviewer and
        named in the result." That needs three things to be true together, and each one
        fails differently on its own: the capability (a role with no `write-tracked` is
        being asked for work the runtime flags at `done`), the boundary (uncertain means
        major, not edit), and the carve-out from the protocol's report-do-not-fix rule,
        which every agent reads several thousand characters earlier."""
        role = roles.load(self.repo)["reviewer"]
        self.assertIn("write-tracked", role.capabilities)
        for expected in ("make it yourself",
                         "Unsure whether a fix is minor? Then it is a major",
                         "Your write authority reaches those minor fixes and nothing else",
                         'not the "something else\nyou noticed" the protocol tells you'
                         .replace("\n", " ")):
            with self.subTest(expected=expected):
                self.assertIn(expected, " ".join(role.prompt.split()))

    def test_qa_reads_the_evidence_that_exists_instead_of_rerunning_it(self):
        """DESIGN-TRUTH: "QA is used only for a specialized environment, perspective or
        scenario that adds coverage; it is not the routine test runner." The old prompt
        described a routine post-implementation stage, which is the slow loop that separates
        a failure from the agent that could fix it. Both halves are pinned: whose the
        ordinary tests are, and what qa does with evidence already bound to the commit."""
        qa = " ".join(roles.load(self.repo)["qa"].prompt.split())
        self.assertIn("the ordinary tests and builds are the author's", qa)
        self.assertIn("Read what was already run on this commit and take it", qa)

    def test_planner_is_a_first_class_bounded_specialist(self):
        """The workflow repair chose a real configured role, not a researcher plus a model
        override and a grant that every caller has to reconstruct. The role owns the seed;
        the plugin command owns the detailed lifecycle."""
        planner = roles.load(self.repo)["planner"]
        self.assertEqual(planner.model, "strong")
        self.assertEqual(planner.capabilities, frozenset({"spawn"}))
        said = " ".join(planner.prompt.split())
        self.assertIn("bounded specialist", said)
        self.assertIn("sb plugin plans planner", said)
        self.assertIn("Before reading the task brief", said)
        self.assertNotIn("write-tracked", planner.capabilities)

    def test_disabling_plans_removes_its_planner_role(self):
        """A plugin-specific role must not survive the commands its prompt tells it to use.
        Role discovery reads enabled plugin directories without importing their code."""
        (self.repo / ".switchboard" / "plugins.toml").write_text(
            'enabled = ["!reset"]\n')
        self.assertNotIn("planner", roles.load(self.repo))

    def test_both_task_owning_roles_are_told_to_finish_the_change_before_proving_it(self):
        """DESIGN-TRUTH: "Implementation is kept coherent before normal verification." A
        worker is the main agent for a whole job as often as a lead is, so the rule cannot
        live in one of them; and the diagnostic carve-out has to travel with it, or the rule
        reads as a ban on running anything while working."""
        r = roles.load(self.repo)
        for name in ("lead", "worker"):
            with self.subTest(role=name):
                said = " ".join(r[name].prompt.split())
                self.assertIn("Make the whole change before you verify it", said)
                self.assertIn("diagnostic", said)

    def test_the_protocol_returns_missing_authority_not_multi_agent_work(self):
        """A universal size rule contradicted both roles whose configured authority is to
        spawn. Hand-back is for missing authority or decisions; role prompts decide when
        authorized delegation earns its cost."""
        said = " ".join(config.protocol(self.repo).split())
        self.assertNotIn("task turns out bigger than one agent", said)
        self.assertIn("authority you do not hold", said)
        self.assertIn("Delegating inside a brief", said)

    def test_read_only_work_is_not_told_to_manufacture_a_commit(self):
        said = " ".join(config.protocol(self.repo).split())
        self.assertIn("if the task produced tracked changes, commit them", said)
        self.assertIn("A read-only report does not invent a commit", said)

    def test_the_universal_verbs_are_taught_once_and_the_roles_only_decide(self):
        """DESIGN-TRUTH's subtractive rule, applied to the three prompts that were breaking
        it: "a rule in both places is paid for twice and drifts". The protocol carries the
        `sb block` two-step, the `sb delegate` / `--name` syntax and the waiting syntax, and
        every agent reads it BEFORE its role file — so a role restating any of them buys
        nothing and gives the two copies room to disagree. `--isolation own` and
        `sb merge <child>` are the same rule one layer further out: they are guidance rows
        that fire at the delegate itself, and a rule that moves to the ledger is deleted
        from the spawn prompt.

        What the roles keep is their own decision — which part gets a worker, that a fan-out
        is one cohort to synthesise, what a block is FOR — and, at the block, the clause
        naming the CHAT, which the test above requires and which is not a procedure."""
        p = config.protocol(self.repo)
        r = roles.load(self.repo)
        for canonical in ("--name", "sb waiting --all", "ONE short line"):
            with self.subTest(protocol=canonical):
                self.assertIn(canonical, p)
        for name in ("lead", "worker", "dispatcher"):
            said = r[name].prompt
            for restated in ("--name", "short line", "sb waiting", "--isolation own",
                             "sb merge"):
                with self.subTest(role=name, restated=restated):
                    self.assertNotIn(restated, said)
        # The ledger rows that own the two isolation rules are still there to own them.
        rows = (config.defaults_dir() / "guidance.toml").read_text()
        self.assertIn("isolation-at-the-spawn", rows)
        self.assertIn("merge-finished-isolated-child", rows)

    def test_the_agent_tool_warning_is_universal_and_not_repeated_in_lead(self):
        p = config.protocol(self.repo)
        for phrase in (
            "always means a switchboard agent",
            "built-in subagent or task tool",
            "invisible to everyone but you",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, p)
        texts = [p] + [r.prompt for r in roles.load(self.repo).values()]
        self.assertEqual(1, sum(t.count("nobody can see those, message them, or resume them")
                                for t in texts))
        lead = roles.load(self.repo)["lead"].prompt
        self.assertIn("switchboard meaning defined in the protocol", lead)

    def test_a_reviewers_fixes_stop_at_a_commit(self):
        """Seeding `write-tracked` made the reviewer the first role that produces commits,
        and the protocol's shipping default — branch, push, open the pull request — is read
        by every agent thousands of characters earlier and is written for the agent that
        OWNS the work. A reviewer is usually a tab on the author's in-flight branch, so
        without this the composed default is push-and-PR on somebody else's unfinished
        work. `house-rules` closes it on this repo only, and that file does not ship."""
        said = " ".join(roles.load(self.repo)["reviewer"].prompt.split())
        self.assertIn("Your fixes STOP at that commit", said)
        self.assertIn("do not push", said)
        self.assertIn("do not open a pull request", said)

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

        Every shipped role now, where this was four: `reviewer` has a tier of its own,
        `worker`'s `default` stopped being an unmade choice once every shipped Claude tier
        pinned a concrete id, and `builder` arrived on a codex tier.

        `planner` is here as well and is the one entry that does not come from
        `defaults/roles/`: the plans plugin contributes it and ships enabled, so it is
        part of the table the spawn layer actually sees.

        Asserted as (provider, model, effort) and not as CLI flags, because a tier can name
        a provider whose flags are not Claude's. The flags are still checked underneath, on
        the two tiers that differ in shape.

        NO SHIPPED ROLE IS ON CODEX any more: `builder` was, on `gpt-5.6-sol`, and moved to
        `opus-5-medium` on 2026-09-01 when that pin was retired in favour of naming
        `gpt-luna-max-effort` per spawn. The codex tiers still exist and nothing pins one.

        Pinned as a DECISION, not as behaviour.
        """
        r = roles.load(self.repo)
        want = {
            "dispatcher": ("claude", "claude-opus-4-8", "medium"),
            "lead":       ("claude", "claude-opus-4-8", "medium"),
            "researcher": ("claude", "claude-sonnet-5", "medium"),
            "qa":         ("claude", "claude-sonnet-5", "high"),
            "reviewer":   ("claude", "claude-sonnet-5", "high"),
            "worker":     ("claude", "claude-opus-5",   None),
            "builder":    ("claude", "claude-opus-5",   "medium"),
            "planner":    ("claude", "claude-opus-5",   "high"),
        }
        got = {}
        for name in want:
            spec = roles.get(r, name).spec()
            got[name] = (spec.provider, spec.model, spec.effort)
        self.assertEqual(got, want)

        self.assertEqual(roles.get(r, "qa").spec().cli_args(),
                         ["--model", "claude-sonnet-5", "--effort", "high"])
        self.assertEqual(roles.get(r, "worker").spec().cli_args(),
                         ["--model", "claude-opus-5"])

    def test_a_gated_tier_is_refused_at_the_role_that_asked_for_it(self):
        """`Role.spec()` is where a tier and the role about to run it are both in hand.

        Two refusals, and they are different kinds. The SWITCH is config — the tier ships
        OFF, and a repo that sets `[routing] gpt_luna_direct_enabled` true hands it to
        every role allowed it at once. The ROLE list is the mechanical half of the
        direct-path rule: an agent that splits work, routes it or judges somebody else's
        change may not have this tier, whoever names it, while the two implementation
        leaves may.

        The judgment half — whether a job actually IS direct-path — is deliberately not
        here and cannot be: it is a fact about content, written in the plan guide.
        """
        tier = "gpt-luna-max-effort"
        settings = self.repo / ".switchboard" / "settings.toml"
        with self.assertRaises(models.ModelConfigError) as cm:
            roles.load(self.repo)["worker"].spec(tier)      # off, the shipped default
        self.assertIn("routing.gpt_luna_direct_enabled", str(cm.exception))

        settings.write_text("[routing]\ngpt_luna_direct_enabled = true\n")  # opted in
        r = roles.load(self.repo)
        for role in ("lead", "dispatcher", "reviewer"):
            with self.subTest(role=role), \
                    self.assertRaises(models.ModelConfigError) as cm:
                roles.get(r, role).spec(tier)
            self.assertIn(role, str(cm.exception))
        for role in ("worker", "builder"):
            with self.subTest(role=role):
                spec = roles.get(r, role).spec(tier)
                self.assertEqual((spec.provider, spec.model, spec.effort),
                                 ("codex", "gpt-5.6-luna", "max"))

    def test_an_override_replaces_the_roles_tier(self):
        """`sb delegate --model <tier>` picks another tier, not another mechanism."""
        r = roles.load(self.repo)
        spec = roles.get(r, "researcher").spec("strong")     # the role's own tier is cheap
        self.assertEqual(spec.cli_args(), ["--model", "claude-opus-5", "--effort", "high"])

    def test_a_role_never_hands_out_a_bare_model_id(self):
        """model_id() is gone: it dropped effort, and every caller of it was a bug."""
        self.assertFalse(hasattr(roles.Role("worker"), "model_id"))




if __name__ == "__main__":
    unittest.main()
