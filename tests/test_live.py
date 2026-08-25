"""The live-process check — is anything actually working in this directory.

The most safety-critical component of the teardown design, and the one with the least
evidence behind it: a destructive command will eventually refuse or proceed on what this
says. Two properties are the whole point and both are pinned here.

"Nothing is running" and "I could not tell" must be different answers, structurally — a
scan that failed is not an empty one, because the failure is exactly what happens when the
gate is most needed. And containment is component-wise: sibling checkout names nest as
strings on this machine right now, so a prefix test reads one workspace's processes as
another's.
"""

from __future__ import annotations

import os
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import live  # noqa: E402

# The real shape, taken verbatim from a scan of this machine: strict repeating four-line
# groups, one per process.
SAMPLE = "p339\ncPowerChime\nfcwd\nn/\np73823\ncsleep\nfcwd\nn/private/tmp/work\n"


class Parsing(unittest.TestCase):
    def test_the_real_output_shape_parses(self):
        procs = live._parse(SAMPLE)
        self.assertEqual([p.pid for p in procs], [339, 73823])
        self.assertEqual(procs[1].command, "sleep")
        self.assertEqual(procs[1].cwd, "/private/tmp/work")

    def test_no_processes_is_an_empty_answer_not_a_failure(self):
        self.assertEqual(live._parse(""), [])

    def test_a_truncated_group_is_a_failure_not_a_short_answer(self):
        """The distinction the refuse-on-failure rule rests on. A lenient parser that
        scraped the `n` lines it recognised would call this "nothing here"."""
        self.assertIsNone(live._parse("p339\ncPowerChime\nfcwd\n"))

    def test_output_that_is_not_the_expected_shape_is_a_failure(self):
        self.assertIsNone(live._parse("p339\ncPowerChime\nfcwd\nnrelative/path\n"))
        self.assertIsNone(live._parse("339\nPowerChime\nfcwd\nn/\n"))
        self.assertIsNone(live._parse("pnotanumber\ncx\nfcwd\nn/\n"))


class Scanning(unittest.TestCase):
    def test_a_missing_binary_is_unknown_rather_than_a_crash(self):
        """With an argv list and no shell this raises FileNotFoundError rather than
        returning a non-zero exit, so a refusal that only read `returncode` would crash
        where it meant to refuse."""
        live.CWD_SCAN, keep = ("definitely-not-a-real-binary",), live.CWD_SCAN
        try:
            self.assertIsNone(live.scan())
        finally:
            live.CWD_SCAN = keep

    def test_a_timeout_is_unknown_and_never_a_retry(self):
        live.CWD_SCAN, keep = ("sleep", "5"), live.CWD_SCAN
        try:
            self.assertIsNone(live.scan(timeout=0.1))
        finally:
            live.CWD_SCAN = keep

    @unittest.skipUnless(shutil.which("lsof"), "lsof is what this check is built on")
    def test_the_real_scan_finds_this_process_in_its_own_directory(self):
        """Run in anger, not simulated: the invocation itself, on this machine, against a
        directory something is genuinely sitting in.

        `live.CWD_SCAN` asks for the fd field explicitly (`-F pcnf`): lsof >= 4.94
        stopped emitting the `f` line unless asked, and with it the strict four-line
        group (`p`/`c`/`fcwd`/`n`) holds on lsof 4.93 and earlier as well as on the lsof
        >= 4.94 that Ubuntu 24.04 and Debian 12 ship — so the real invocation runs on
        Linux too. CI's ubuntu-latest runners carry exactly the affected version, which
        is why this test now proves the fix where it bit.
        """
        here = str(Path.cwd())
        found = live.processes_in(here)
        self.assertIsNotNone(found, "lsof answered, so this must not be 'cannot tell'")
        self.assertTrue(any(p.pid == os.getpid() for p in found))

    def test_the_scan_asks_for_the_fd_field_explicitly(self):
        """The regression that would turn CI red on lsof >= 4.94 but stay green locally
        on lsof 4.93: without `f` in the `-F` argument, `_parse`'s strict four-line group
        never matches there and the teardown gate degrades to permanently blind (issue
        #172)."""
        flag = live.CWD_SCAN[live.CWD_SCAN.index("-F") + 1]
        self.assertIn("f", flag)


class Containment(unittest.TestCase):
    """The nesting is real, not constructed: sibling worktrees of this repo sit side by
    side under one directory, and `git worktree list` has repeatedly held a pair like
    `.../fix-options` and `.../fix-options-2` at once. The root here is this checkout's
    own path, so the shape is a real one on whatever machine the suite runs on."""

    root = str(Path(__file__).resolve().parent.parent)

    def test_a_sibling_whose_name_is_a_string_prefix_is_not_under_it(self):
        self.assertTrue(f"{self.root}-2/anything".startswith(self.root))   # the trap
        self.assertFalse(live.is_under(f"{self.root}-2/anything", self.root))

    def test_a_real_child_is_under_it(self):
        self.assertTrue(live.is_under(f"{self.root}/switchboard/store.py", self.root))

class Filtering(unittest.TestCase):
    def setUp(self):
        self.keep = live.scan

    def tearDown(self):
        live.scan = self.keep

    def test_a_process_in_the_directory_is_reported(self):
        live.scan = lambda *a, **kw: [live.Proc(11, "vim", "/wt/api/switchboard")]
        self.assertEqual([p.pid for p in live.processes_in("/wt/api")], [11])

    def test_a_scan_that_failed_is_unknown_and_not_empty(self):
        live.scan = lambda *a, **kw: None
        self.assertIsNone(live.processes_in("/wt/api"))

    def test_every_pid_in_the_directory_is_reported_and_none_is_left_out(self):
        """Containment is the whole of what this does. Leaving the caller's own tree out is
        the gate's business, on the answer this gives back — `_live_under` reads the process
        table to know which pids those are, and this cannot."""
        live.scan = lambda *a, **kw: [live.Proc(11, "sb", "/wt/api"),
                                      live.Proc(12, "vim", "/wt/api")]
        self.assertEqual([p.pid for p in live.processes_in("/wt/api")], [11, 12])


if __name__ == "__main__":
    unittest.main()
