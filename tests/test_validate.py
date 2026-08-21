"""Argument validation, and the CLI boundary that applies it.

Two things are being protected. herdr's agent-name rule (`[a-z][a-z0-9_-]{0,31}`), and
its refusal of a newline in ANY agent argument — both of which otherwise surface far from
the flag that caused them, or as a shell that hangs for the full timeout.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import store, validate  # noqa: E402
from switchboard.cli import _validate, build_parser  # noqa: E402


def parse(argv):
    return build_parser().parse_args(argv)


class AgentNameTest(unittest.TestCase):
    def test_herdrs_rule_is_the_rule(self):
        for good in ("main", "w", "qa-bot-1", "worker_2", "a" * 32):
            self.assertEqual(validate.agent_name(good), good)

    def test_illegal_names_are_refused(self):
        for bad in ("QA", "1st", "-lead", "has space", "accént", "a" * 33, "", "  "):
            with self.assertRaises(validate.Invalid, msg=bad):
                validate.agent_name(bad)

    def test_the_error_names_the_rule_and_offers_a_fix(self):
        with self.assertRaises(validate.Invalid) as e:
            validate.agent_name("QA Bot", "--name")
        msg = str(e.exception)
        self.assertIn("--name", msg)
        self.assertIn("[a-z][a-z0-9_-]{0,31}", msg)
        self.assertIn("'qa-bot'", msg)          # the suggestion is itself legal

    def test_too_long_says_so_rather_than_blaming_the_characters(self):
        with self.assertRaises(validate.Invalid) as e:
            validate.agent_name("a" * 40)
        self.assertIn("over the 32", str(e.exception))


class SlugTest(unittest.TestCase):
    def test_a_role_a_human_would_write_becomes_a_legal_name(self):
        self.assertEqual(validate.slug_name("QA Bot"), "qa-bot")
        self.assertEqual(validate.slug_name("Reviewer #2!"), "reviewer-2")
        self.assertEqual(validate.slug_name("feature/api-v2"), "feature-api-v2")

    def test_reserve_holds_room_for_the_suffix_the_caller_will_add(self):
        long = "x" * 60
        got = validate.slug_name(long, reserve=len("-lead"))
        self.assertEqual(len(got), 32 - len("-lead"))
        self.assertRegex(got + "-lead", validate.AGENT_NAME)

    def test_every_slug_is_a_legal_agent_name(self):
        for raw in ("QA Bot", "2fa", "---", "a" * 99, "Ünicode Ünly", "x/y\\z"):
            self.assertEqual(validate.agent_name(validate.slug_name(raw)),
                             validate.slug_name(raw))


class LineTest(unittest.TestCase):
    def test_a_newline_is_refused_with_the_reason(self):
        with self.assertRaises(validate.Invalid) as e:
            validate.line("do this\nand that", "task")
        msg = str(e.exception)
        self.assertIn("task", msg)
        self.assertIn("single line", msg)
        self.assertIn("invalid_agent_argument", msg)   # what herdr would have said

    def test_the_cap_is_enforced_and_names_the_alternative(self):
        with self.assertRaises(validate.Invalid) as e:
            validate.line("x" * (validate.MAX_TEXT + 1), "task")
        self.assertIn("4000", str(e.exception))
        self.assertIn("path", str(e.exception))
        self.assertEqual(len(validate.line("x" * validate.MAX_TEXT, "task")),
                         validate.MAX_TEXT)

    def test_control_characters_are_refused(self):
        with self.assertRaises(validate.Invalid):
            validate.line("hello\x00world", "task")
        with self.assertRaises(validate.Invalid):
            validate.line("clear\x1b[2Jscreen", "task")


class ReasonTest(unittest.TestCase):
    """`sb block "<why>"`. The one rule here that is ours: the human never reads this
    field, so a reason big enough to BE the message is an answer sent nowhere — and the
    agent cannot tell, because the block succeeded."""

    def test_the_cap_is_far_below_ordinary_text(self):
        """Sized off the caps, not literals: a report must not fit, and a real reason
        must never be near the edge."""
        self.assertLess(validate.MAX_BLOCK_REASON, validate.MAX_TEXT)
        self.assertEqual(len(validate.reason("x" * validate.MAX_BLOCK_REASON)),
                         validate.MAX_BLOCK_REASON)
        with self.assertRaises(validate.Invalid):
            validate.reason("x" * (validate.MAX_BLOCK_REASON + 1))

    def test_a_report_flattened_onto_one_line_is_still_refused(self):
        """The actual misuse, and its second act. A multi-paragraph answer was refused for
        its newlines, so it was flattened into one run-on line and got through. Both
        shapes must fail, or the newline check only teaches the workaround."""
        report = ("Findings: the spawn path drops every system prompt but the last. "
                  "Questions: 1. do we fix spawn first? I recommend yes. "
                  "2. do we ship the prompts anyway? I recommend no. ") * 3
        for shape in (report, report.replace(". ", ".\n\n", 4)):
            with self.assertRaises(validate.Invalid, msg=shape[:40]):
                validate.reason(shape)

    def test_both_refusals_name_the_chat_and_forbid_shortening(self):
        """The error is the only teaching moment that cannot be forgotten, so it carries
        the fix. It must NOT blame herdr's newline rule: that reads as a formatting
        complaint, and the answer to a formatting complaint is to flatten and resend."""
        for bad in ("stuck\nbadly", "x" * (validate.MAX_BLOCK_REASON + 1)):
            with self.assertRaises(validate.Invalid) as e:
                validate.reason(bad)
            msg = str(e.exception)
            self.assertIn("chat", msg)              # where the message actually goes
            self.assertIn("shorten", msg)           # and the wrong way out of the refusal
            self.assertNotIn("invalid_agent_argument", msg)
            self.assertNotIn("herdr", msg)

    def test_the_refusal_does_not_hand_back_a_shape_to_copy(self):
        """Read at the moment the agent is composing for a human, so anything copyable in
        it anchors harder than the protocol does (DESIGN-TRUTH 2026-08-14: none of the
        human-facing rules may become something to copy). It says where the message goes,
        never what is in it, and offers no specimen call to imitate."""
        with self.assertRaises(validate.Invalid) as e:
            validate.reason("x" * (validate.MAX_BLOCK_REASON + 1))
        msg = str(e.exception)
        for shape in ("numbered", "findings", "recommend", "options"):
            self.assertNotIn(shape, msg.lower())
        self.assertNotIn('"', msg)                  # no worked example of the call

class RefNameTest(unittest.TestCase):

    def test_git_would_reject_these_so_we_do_first(self):
        for bad in ("", "  ", "has space", "a..b", "-lead", "/abs", ".hidden",
                    "trailing/", "ends.", "work.lock", "a//b", "head@{0}", "@",
                    "star*", "colon:name", "x" * 300, "nl\nname"):
            with self.assertRaises(validate.Invalid, msg=bad):
                validate.ref_name(bad)

    def test_the_error_says_it_is_a_branch_name_and_suggests_one(self):
        with self.assertRaises(validate.Invalid) as e:
            validate.ref_name("My Feature")
        msg = str(e.exception)
        self.assertIn("git branch name", msg)
        self.assertIn("my-feature", msg)


class TargetTest(unittest.TestCase):

    def test_a_typo_is_caught_at_the_boundary(self):
        with self.assertRaises(validate.Invalid):
            validate.targets(["worker-1", "Reviewer"])

class CliBoundaryTest(unittest.TestCase):
    """`_validate` runs on the parsed namespace before anything is spawned or written."""

    def bad(self, argv):
        with self.assertRaises(validate.Invalid, msg=" ".join(argv)):
            _validate(parse(argv))

    def test_delegate_rejects_a_multi_line_task(self):
        self.bad(["delegate", "step one\nstep two"])

    def test_delegate_takes_a_topic_in_prose_and_refuses_only_a_multi_line_one(self):
        """`--name` is the SUBJECT, not the name — `Broker._compose_name` puts the role in
        front of it and slugs the pair, so spaces and capitals are its job and not this
        boundary's. What is still refused here is what herdr refuses in any argument."""
        args = parse(["delegate", "do it", "--name", "  QA Bot  "])
        _validate(args)
        self.assertEqual(args.name, "QA Bot")
        self.bad(["delegate", "do it", "--name", "two\nlines"])

    def test_delegate_rejects_a_multi_line_ad_hoc_role_prompt(self):
        self.bad(["delegate", "do it", "--as", "you are\na reviewer"])
        self.bad(["delegate", "do it", "--with", "be terse\nand fast"])

    def test_delegate_normalises_what_it_accepts(self):
        args = parse(["delegate", "  do it  ", "--with", " be terse "])
        _validate(args)
        self.assertEqual(args.task, "do it")
        self.assertEqual(args.with_, ["be terse"])

    def test_empty_strings_are_caught_for_every_verb_that_takes_prose(self):
        self.bad(["delegate", "   "])
        self.bad(["done", "   "])
        self.bad(["block", "\t"])
        self.bad(["tell", "worker-1", "  "])

    def test_done_and_block_must_be_one_line(self):
        # Both reach herdr as `report-agent --message`.
        self.bad(["done", "fixed it\nand tested it"])
        self.bad(["block", "stuck\nbadly"])

    def test_block_at_the_boundary_refuses_a_reason_shaped_like_a_report(self):
        """A summary of any length is legal; a block reason of any length is not. The verb
        is where the misuse is visible, so this must fail before anything is written."""
        long = "the whole answer, " * 40
        self.bad(["block", long])
        args = parse(["done", long])
        _validate(args)                              # `done` is a report and may be long
        self.assertEqual(args.summary, long.strip())
        args = parse(["block", "  need a decision on the auth split  "])
        _validate(args)
        self.assertEqual(args.why, "need a decision on the auth split")

    def test_a_message_body_may_wrap_but_a_task_may_not(self):
        args = parse(["tell", "worker-1", "line one\nline two"])
        _validate(args)                      # stored and read back via `sb inbox`
        self.assertIn("\n", args.message)
        self.bad(["delegate", "line one\nline two"])

    def test_recipients_are_checked_before_the_message_is_written(self):
        self.bad(["tell", "No-Such-Agent", "anyone home?"])
        self.bad(["tell", "worker-1", "Reviewer", "hi"])   # last positional is the message

    def test_parent_and_human_stay_addressable(self):
        for who in ("parent", "human"):
            args = parse(["tell", who, "what now?"])
            _validate(args)
            self.assertEqual(args.who, [who])

    def test_workspace_names_are_branch_names(self):
        """`sb workspace close` and `--workspace` are what name one now: `sb workspace
        new` is deleted, and the rule it was held to travels to the verbs that stayed."""
        self.bad(["workspace", "close", "My Feature"])
        self.bad(["delegate", "t", "--workspace", "no space"])
        args = parse(["workspace", "close", "feature/api-v2"])
        _validate(args)
        self.assertEqual(args.name, "feature/api-v2")

    def test_the_interrupt_verb_is_gone_and_the_mode_replaces_it(self):
        """Item 3.2. Interrupting is a delivery mode of `tell`, and DESIGN-TRUTH's
        rejected list says the verb is not a second way to spell it. Both halves are
        checked here: an agent typing the old verb is told plainly by argparse, and the
        capability it used to reach is still reachable."""
        with self.assertRaises(SystemExit):
            parse(["interrupt", "worker-1", "stop"])
        args = parse(["tell", "worker-1", "stop", "--interrupt"])
        _validate(args)
        self.assertEqual(args.mode, "interrupt")

    def test_the_ask_verb_is_gone(self):
        """Item 3.6. It blocked its caller in a poll loop, which is the one thing
        DESIGN-TRUTH forbids outright — no agent ever waits on another agent. What
        replaces it is a `tell --needs-reply`, which returns immediately."""
        with self.assertRaises(SystemExit):
            parse(["ask", "worker-1", "ready?"])
        from switchboard import broker as broker_mod
        self.assertFalse(hasattr(broker_mod.Broker, "ask"))

    def test_agent_lookups_are_checked_too(self):
        self.bad(["restore", "Not A Name"])
        self.bad(["tell", "Worker", "stop", "--interrupt"])
        self.bad(["tell", "worker-1", "stop\nnow", "--interrupt"])
        self.bad(["inspect", "worker-1", "-n", "0"])
        self.bad(["log", "--agent", "Worker"])

    def test_verbs_with_nothing_to_check_are_untouched(self):
        for argv in (["status"], ["inbox"], ["doctor"], ["init"], ["presets"],
                     ["cleanup"], ["start"]):
            _validate(parse(argv))           # must not raise


if __name__ == "__main__":
    unittest.main()
