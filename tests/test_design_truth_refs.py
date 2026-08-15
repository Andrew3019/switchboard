"""The line-range citations into `DESIGN-TRUTH.md`, checked against the document.

Code, prompts and tests cite the trusted document by line range — `DESIGN-TRUTH.md:133-136`
— because a claim about what the design says is worth being able to open. The citations rot
silently: nothing reads them, so an edit to the document moves every entry below it and the
references keep pointing confidently at whatever now occupies those lines. That is exactly
what happened when the document was rewritten for the dispatcher/lead split — about ten of
them ended up on unrelated entries, and one had been wrong for long enough that nobody could
say when.

The check is structural: an entry in that document begins with `**` and ends where a blank
line follows, so a citation must start on the first line of an entry and end on the last
line of one. Both ends, because checking only the start was measured against a five-line
insertion and let four citations in thirteen pass while pointing at the wrong entry — a
shift that lands on any `**` at all satisfied it. Requiring the far end to land on a
boundary too means a wrong range has to coincide with two boundaries at once.

WHAT IT STILL CANNOT DO, written here rather than left to be discovered: it cannot tell a
right entry from a wrong one. A shift that happens to align at both ends passes, and so does
a citation that was aimed at the wrong entry the day it was written. The durable fix is not
a cleverer test — it is to stop citing by line number and cite by the entry's own opening
words, which do not move. That is a change to a convention used at two dozen sites and to
how everyone writes the next one, so it is a decision for Andrew rather than something to
slip into a review branch. Until then: this catches the rot that has actually happened here,
and a reader who follows a citation and lands somewhere surprising should trust their eyes
over the suite.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "DESIGN-TRUTH.md"

# Where citations are allowed to live. `research/` is a frozen record of what was read
# before any of this was built and is not maintained against the document.
SEARCHED = ("switchboard", "tests", "defaults", "acceptance")
SUFFIXES = (".py", ".md", ".toml")

CITE = re.compile(r"DESIGN-TRUTH(?:\.md)?:(\d+)(?:-(\d+))?")


def _citations():
    for top in SEARCHED:
        for path in sorted((ROOT / top).rglob("*")):
            if path.suffix not in SUFFIXES or "__pycache__" in path.parts:
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                for m in CITE.finditer(line):
                    start = int(m.group(1))
                    yield path.relative_to(ROOT), n, start, int(m.group(2) or start)


class DesignTruthCitationsTest(unittest.TestCase):
    def setUp(self):
        self.lines = DOC.read_text().splitlines()
        self.cites = list(_citations())

    def test_there_are_citations_to_check(self):
        """Guards the guard: a regex that matches nothing passes everything."""
        self.assertGreater(len(self.cites), 10)

    def _ends_a_block(self, n: int) -> bool:
        """Line `n` (1-based) is the last line before a blank one, or the last line."""
        return n == len(self.lines) or not self.lines[n].strip()

    def test_every_cited_range_starts_on_an_entry_and_is_inside_the_document(self):
        for where, line_no, start, end in self.cites:
            with self.subTest(f"{where}:{line_no}"):
                self.assertLessEqual(end, len(self.lines),
                                     "citation runs past the end of DESIGN-TRUTH.md")
                self.assertLessEqual(start, end)
                self.assertTrue(
                    self.lines[start - 1].startswith("**"),
                    f"DESIGN-TRUTH.md:{start} is not the start of an entry — it reads "
                    f"{self.lines[start - 1][:60]!r}")
                self.assertTrue(
                    self._ends_a_block(end),
                    f"DESIGN-TRUTH.md:{end} is not the end of one — it reads "
                    f"{self.lines[end - 1][:60]!r} with more of the same block after it")


if __name__ == "__main__":
    unittest.main()
