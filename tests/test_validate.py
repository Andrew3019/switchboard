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
from switchboard.cli import _derived_name, _validate, build_parser  # noqa: E402


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

    def test_a_name_must_start_with_a_letter(self):
        self.assertEqual(validate.slug_name("2fa"), "w-2fa")
        self.assertEqual(validate.slug_name("_private"), "private")   # stripped, not prefixed

    def test_nothing_usable_still_produces_a_legal_name(self):
        for junk in ("", "   ", "!!!", "中文"):
            self.assertRegex(validate.slug_name(junk), validate.AGENT_NAME)

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

    def test_a_carriage_return_counts_as_a_newline(self):
        with self.assertRaises(validate.Invalid):
            validate.line("a\r\nb", "task")

    def test_whitespace_only_is_empty(self):
        for blank in ("", "   ", "\n", "\t\n "):
            with self.assertRaises(validate.Invalid, msg=repr(blank)):
                validate.line(blank, "summary")

    def test_surrounding_whitespace_is_stripped_not_rejected(self):
        self.assertEqual(validate.line("  ship it  ", "summary"), "ship it")

    def test_the_cap_is_enforced_and_names_the_alternative(self):
        with self.assertRaises(validate.Invalid) as e:
            validate.line("x" * (validate.MAX_TEXT + 1), "task")
        self.assertIn("4000", str(e.exception))
        self.assertIn("path", str(e.exception))
        self.assertEqual(len(validate.line("x" * validate.MAX_TEXT, "task")),
                         validate.MAX_TEXT)

    def test_prompts_get_a_larger_cap_than_traffic(self):
        big = "x" * 6_000
        with self.assertRaises(validate.Invalid):
            validate.line(big, "task")
        self.assertEqual(validate.line(big, "--as", max_len=validate.MAX_PROMPT), big)

    def test_control_characters_are_refused(self):
        with self.assertRaises(validate.Invalid):
            validate.line("hello\x00world", "task")
        with self.assertRaises(validate.Invalid):
            validate.line("clear\x1b[2Jscreen", "task")


class TextTest(unittest.TestCase):
    """Message bodies never become a herdr argument, so they may wrap."""

    def test_newlines_are_allowed(self):
        self.assertEqual(validate.text("one\ntwo", "message"), "one\ntwo")

    def test_but_empty_is_not(self):
        for blank in ("", "  \n  "):
            with self.assertRaises(validate.Invalid):
                validate.text(blank, "message")

    def test_none_is_reported_as_missing_not_as_a_crash(self):
        with self.assertRaises(validate.Invalid) as e:
            validate.text(None, "message")
        self.assertIn("required", str(e.exception))


class RefNameTest(unittest.TestCase):
    def test_ordinary_branch_names_pass(self):
        for good in ("main", "feature/api-v2", "release-1.2", "andrew/fix_thing"):
            self.assertEqual(validate.ref_name(good), good)

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
    def test_addresses_are_not_agent_names_but_are_valid(self):
        self.assertEqual(validate.targets(["parent", "human"]), ["parent", "human"])

    def test_a_typo_is_caught_at_the_boundary(self):
        with self.assertRaises(validate.Invalid):
            validate.targets(["worker-1", "Reviewer"])

    def test_several_recipients_come_back_in_order(self):
        self.assertEqual(validate.targets(["b", "a"]), ["b", "a"])


class PositiveIntTest(unittest.TestCase):
    def test_zero_and_negative_are_refused(self):
        for n in (0, -1):
            with self.assertRaises(validate.Invalid):
                validate.positive_int(n, "--timeout")

    def test_a_normal_value_passes_through(self):
        self.assertEqual(validate.positive_int(900, "--timeout"), 900)


class CliBoundaryTest(unittest.TestCase):
    """`_validate` runs on the parsed namespace before anything is spawned or written."""

    def bad(self, argv):
        with self.assertRaises(validate.Invalid, msg=" ".join(argv)):
            _validate(parse(argv))

    def test_delegate_rejects_a_multi_line_task(self):
        self.bad(["delegate", "step one\nstep two"])

    def test_delegate_rejects_an_illegal_explicit_name(self):
        self.bad(["delegate", "do it", "--name", "QA Bot"])

    def test_delegate_rejects_a_multi_line_ad_hoc_role_prompt(self):
        self.bad(["delegate", "do it", "--as", "you are\na reviewer"])
        self.bad(["delegate", "do it", "--with", "be terse\nand fast"])

    def test_delegate_normalises_what_it_accepts(self):
        args = parse(["delegate", "  do it  ", "--with", " be terse "])
        _validate(args)
        self.assertEqual(args.task, "do it")
        self.assertEqual(args.with_, ["be terse"])

    def test_a_role_that_is_not_a_legal_name_is_still_accepted(self):
        """It is a roles.toml lookup key, not a name — the NAME is slugified instead."""
        args = parse(["delegate", "do it", "--role", "QA Bot"])
        _validate(args)
        self.assertEqual(args.role, "QA Bot")

    def test_empty_strings_are_caught_for_every_verb_that_takes_prose(self):
        self.bad(["delegate", "   "])
        self.bad(["done", "   "])
        self.bad(["block", "\t"])
        self.bad(["tell", "worker-1", "  "])
        self.bad(["ask", "worker-1", ""])

    def test_done_and_block_must_be_one_line(self):
        # Both reach herdr as `report-agent --message`.
        self.bad(["done", "fixed it\nand tested it"])
        self.bad(["block", "stuck\nbadly"])

    def test_a_message_body_may_wrap_but_a_task_may_not(self):
        args = parse(["tell", "worker-1", "line one\nline two"])
        _validate(args)                      # stored and read back via `sb inbox`
        self.assertIn("\n", args.message)
        self.bad(["delegate", "line one\nline two"])

    def test_ask_rejects_a_useless_timeout(self):
        self.bad(["ask", "worker-1", "ready?", "--timeout", "0"])

    def test_recipients_are_checked_before_the_blocking_call(self):
        self.bad(["ask", "No-Such-Agent", "anyone home?"])
        self.bad(["tell", "worker-1", "Reviewer", "hi"])   # last positional is the message

    def test_parent_and_human_stay_addressable(self):
        for who in ("parent", "human"):
            args = parse(["ask", who, "what now?"])
            _validate(args)
            self.assertEqual(args.who, [who])

    def test_workspace_names_are_branch_names(self):
        self.bad(["workspace", "new", "My Feature"])
        self.bad(["workspace", "new", "ok", "--base", "no space"])
        self.bad(["workspace", "new", "ok", "--agent", "Lead"])
        args = parse(["workspace", "new", "feature/api-v2"])
        _validate(args)
        self.assertEqual(args.name, "feature/api-v2")

    def test_agent_lookups_are_checked_too(self):
        self.bad(["restore", "Not A Name"])
        self.bad(["interrupt", "Worker", "stop"])
        self.bad(["interrupt", "worker-1", "stop\nnow"])
        self.bad(["inspect", "worker-1", "-n", "0"])
        self.bad(["wait", "Worker"])
        self.bad(["log", "--agent", "Worker"])

    def test_verbs_with_nothing_to_check_are_untouched(self):
        for argv in (["status"], ["inbox"], ["doctor"], ["init"], ["presets"],
                     ["cleanup", "--all-idle"], ["start"]):
            _validate(parse(argv))           # must not raise


class DerivedNameTest(unittest.TestCase):
    """The other half of the agent-name problem: names nobody typed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = store.connect(path=Path(self.tmp.name) / "state.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_a_legal_role_is_left_to_the_broker(self):
        self.assertIsNone(_derived_name(self.db, "worker"))

    def test_an_illegal_role_gets_a_legal_derived_name(self):
        got = _derived_name(self.db, "QA Bot")
        self.assertEqual(got, "qa-bot-1")
        self.assertEqual(validate.agent_name(got), got)

    def test_it_picks_the_first_free_number_like_the_broker_does(self):
        store.create_agent(self.db, name="qa-bot-1", role="QA Bot")
        self.assertEqual(_derived_name(self.db, "QA Bot"), "qa-bot-2")

    def test_an_over_long_role_cannot_overflow_the_name(self):
        got = _derived_name(self.db, "R" * 40)
        self.assertLessEqual(len(got), validate.MAX_AGENT_NAME)
        self.assertEqual(validate.agent_name(got), got)


if __name__ == "__main__":
    unittest.main()
