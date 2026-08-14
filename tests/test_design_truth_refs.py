"""The line-range citations into `DESIGN-TRUTH.md`, checked against the document.

Code, prompts and tests cite the trusted document by line range — `DESIGN-TRUTH.md:130-133`
— because a claim about what the design says is worth being able to open. The citations rot
silently: nothing reads them, so an edit to the document moves every entry below it and the
references keep pointing confidently at whatever now occupies those lines. That is exactly
what happened when the document was rewritten for the dispatcher/lead split — about ten of
them ended up on unrelated entries, and one had been wrong for long enough that nobody could
say when.

The check is deliberately weak: an entry in that document begins with `**`, so a range that
starts on one is pointing at the top of *an* entry rather than into the middle of a
paragraph. It cannot tell whether it is the RIGHT entry — only a human reading both can —
but every rot this repo has actually produced is a range that slid off an entry boundary
entirely, and that is what this catches on the day it happens rather than on the day someone
follows the link.
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


if __name__ == "__main__":
    unittest.main()
