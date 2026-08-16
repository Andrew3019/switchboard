"""The decisions in `stats` that are policy rather than plumbing.

Everything else in that module is a subprocess and a sum, and a test of those would be a
test of `git log` and `ps`. These are not: what counts as docs and which memory pages
count as available each decide a number on screen, and the cache's two boundaries decide
whether that number is a reading or a memory. All of them can be pinned on canned text and
a fake clock, without teaching a fake anything.

Deliberately NOT tested here, and named so the gap is visible rather than assumed: the
`lsof`/`ps` scan and the git walk. Proving those needs real processes in a real repository
— done live, against a clone with agents in it — and a fake that answered them would only
be pinning the fake.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import stats  # noqa: E402


class DocsFilter(unittest.TestCase):
    """Whether a path is prose decides whether its lines reach the `+/-` on screen."""

    def test_prose_by_suffix_and_by_tree(self):
        for path in ("README.md", "notes/board-layout-scout.md", "notes/x/y.txt",
                     "learnings/board-rows.md", "design/probe-findings.md"):
            with self.subTest(path=path):
                self.assertTrue(stats.is_docs(path))

    def test_code_stays_counted_even_when_it_is_named_like_prose(self):
        """The reason the tree match is on the FIRST component: a module called `notes` is
        code, and a `notes/` directory nested inside a package is not the prose tree."""
        for path in ("switchboard/stats.py", "switchboard/notes.py",
                     "tests/notes/test_x.py", "defaults/settings.toml"):
            with self.subTest(path=path):
                self.assertFalse(stats.is_docs(path))

    def test_a_rename_is_judged_on_where_the_file_ended_up(self):
        """`git log --numstat` writes a rename as `dir/{old => new}/file`. Unresolved, that
        string matches neither the suffix nor the tree, so a moved doc would be counted as
        code."""
        self.assertTrue(stats.is_docs("switchboard/{a.py => notes/b.md}"))
        self.assertTrue(stats.is_docs("notes/{old => new}.md"))
        self.assertFalse(stats.is_docs("notes/a.md => switchboard/b.py"))


class NumstatSum(unittest.TestCase):
    OUTPUT = (
        "aaaaaaa\n"
        "\n"
        "10\t5\tswitchboard/stats.py\n"
        "3\t0\tnotes/scout.md\n"
        "bbbbbbb\n"
        "\n"
        "-\t-\tdesign/diagram.png\n"
        "1\t1\tREADME.md\n"
    )

    def test_added_and_deleted_are_summed_separately_and_docs_are_dropped(self):
        """The docs rows (`notes/scout.md`, `README.md`) contribute to neither sum, and the
        binary row contributes to neither either — only `stats.py`'s 10 and 5 survive."""
        got = stats._parse_numstat(self.OUTPUT)
        self.assertEqual(got["added"], 10)
        self.assertEqual(got["deleted"], 5)
        self.assertEqual(got["commits"], 2)

    def test_an_hour_with_no_commits_is_zero_and_not_unknown(self):
        """The one place a zero is honest: git answered, and the answer was nothing."""
        self.assertEqual(stats._parse_numstat("")["added"], 0)
        self.assertEqual(stats._parse_numstat("")["deleted"], 0)


class AvailableMemory(unittest.TestCase):
    """The macOS half, on the one thing about `vm_stat` that is a decision.

    Its output is pages, in classes, and which classes count as available is the whole
    question — inactive pages are reclaimed under pressure and leaving them out reports a
    machine with room as a full one. Pinned on canned output rather than the live command:
    what is being checked is the arithmetic and the class list, not that macOS has `vm_stat`.

    The Linux half is a `/proc/meminfo` read of a number the kernel computes, with nothing
    to decide, and is left to the live check.
    """

    VM_STAT = (
        "Mach Virtual Memory Statistics: (page size of 4096 bytes)\n"
        "Pages free:                                2.\n"
        "Pages active:                          99999.\n"
        "Pages inactive:                            3.\n"
        "Pages speculative:                         5.\n"
        "Pages wired down:                      88888.\n"
    )

    def run_with(self, stdout, returncode=0):
        done = subprocess.CompletedProcess([], returncode, stdout, "")
        with mock.patch.object(stats.subprocess, "run", return_value=done):
            return stats._available_darwin()

    def test_free_inactive_and_speculative_pages_are_what_a_new_allocation_can_have(self):
        self.assertEqual(self.run_with(self.VM_STAT), (2 + 3 + 5) * 4096)

    def test_output_this_does_not_recognise_is_unknown_and_never_a_full_machine(self):
        """A zero here would say the machine has nothing left — a conclusion nobody
        reached. Both failures: no page size, and a page class missing."""
        self.assertIsNone(self.run_with("Pages free: 2.\n"))          # no page size
        self.assertIsNone(self.run_with(
            "Mach Virtual Memory Statistics: (page size of 4096 bytes)\n"
            "Pages free:                                2.\n"))       # classes missing
        self.assertIsNone(self.run_with(self.VM_STAT, returncode=1))


class CacheBoundaries(unittest.TestCase):
    """Fresh, stale-but-usable, and too old — the three states, at their edges.

    A fake clock rather than sleeping: the boundaries are the test, and a real one would
    pin them to within a scheduler's jitter.
    """

    def setUp(self):
        self.t = 1000.0
        self.calls = 0
        self.s = stats.Sampler(ttl=10.0, max_age=30.0, clock=lambda: self.t)
        # The module's own samplers are process-wide singletons. Nothing here touches them,
        # but a test file that leaves them holding a sample would hand the next one a cache.
        self.addCleanup(stats.reset)

    def sample(self):
        self.calls += 1
        return {"n": self.calls}

    def take(self, **kw):
        return self.s.get(self.sample, wait=True, **kw)

    def test_a_value_is_served_until_the_ttl_and_resampled_at_it(self):
        self.assertEqual(self.take()[0], {"n": 1})
        self.t += 9.9
        self.assertEqual(self.take()[0], {"n": 1})   # inside the ttl: no new sample
        self.t += 0.1                                 # exactly at it
        self.assertEqual(self.take()[0], {"n": 2})
        self.assertEqual(self.calls, 2)

    def test_past_max_age_the_value_is_dropped_rather_than_shown(self):
        """The boundary that matters on screen: a CPU figure from ten minutes ago is not a
        dimmer reading, it is a wrong one. A refusal to sample must not leave one there."""
        self.s.get(self.sample, wait=True)
        broken = lambda: None                        # noqa: E731 — every sample fails now
        self.t += 30.0
        value, age = self.s.get(broken, wait=True)
        self.assertEqual(value, {"n": 1})            # AT max_age, still served
        self.assertEqual(age, 30.0)
        self.t += 0.1
        value, age = self.s.get(broken, wait=True)
        self.assertIsNone(value)                     # past it, unknown
        self.assertAlmostEqual(age, 30.1)            # and the age still says why

    def test_a_failed_sample_ages_the_last_one_instead_of_blanking_it(self):
        self.s.get(self.sample, wait=True)
        self.t += 11.0
        value, age = self.s.get(lambda: None, wait=True)
        self.assertEqual(value, {"n": 1})
        self.assertEqual(age, 11.0)

    def test_a_sample_that_raises_is_a_sample_that_did_not_happen(self):
        """Never a traceback out of `collect()`: this runs behind a board that must keep
        drawing whatever git and ps are doing."""
        def boom():
            raise RuntimeError("lsof went away")
        self.assertEqual(self.s.get(boom, wait=True), (None, None))

    def test_nothing_sampled_yet_is_unknown_with_no_age(self):
        self.assertEqual(self.s.get(lambda: None, wait=True), (None, None))
        self.assertTrue(self.s.due())


if __name__ == "__main__":
    unittest.main()
