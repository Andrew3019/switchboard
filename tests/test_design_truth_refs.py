"""The citations into `DESIGN-TRUTH.md`, checked against the words they quote.

Code, prompts and tests cite the trusted document by quoting it — `DESIGN-TRUTH: "The role
list is lightly audited and fine as it is"` — because a claim about what the design says is
worth being able to open, and because the entry's own words do not move when the document is
edited. They used to be cited by line range, and the ranges rotted silently: an edit moved
every entry below it and the references kept pointing confidently at whatever now occupied
those lines. That is exactly what happened when the document was rewritten for the
dispatcher/lead split — about ten ended up on unrelated entries, and one had been wrong for
long enough that nobody could say when.

WHAT A CITATION LOOKS LIKE. `DESIGN-TRUTH:` (or `DESIGN-TRUTH.md:`) followed by one or more
double-quoted strings, joined by `+` when one point needs two entries. The whole citation
lives on one line, because this reads a file a line at a time. The normal quote is the
entry's bold lead-in, which is what makes it a pointer at an entry rather than at a sentence;
quoting a sentence from inside the entry instead is equally valid and is what about two dozen
older citations already do, deliberately, to point at the exact claim they lean on.

THE RULE ENFORCED. Each quoted string must appear verbatim inside a SINGLE entry — matched
against each entry's own text, never against the whole document, so a quote that only exists
because it runs across an entry boundary is a broken citation rather than a passing one.
Whitespace is normalised on both sides, so the document may wrap a sentence wherever it likes.
A quote must also be `MIN_QUOTE` characters or longer, unless it is exactly some entry's
lead-in: a three-word fragment matches by accident and proves nothing, while a genuinely short
lead-in ("`sb wait`.") is still a precise pointer because lead-ins are checked for uniqueness.

WHAT IT STILL CANNOT DO, written here rather than left to be discovered: it cannot tell
whether the prose around a citation characterises the entry correctly. A citation may quote
the right entry and then say something the entry does not support, and that passes — it is a
semantic judgement, not a structural one. What it CAN now catch, and the line-range check
could not, is content drift: reword an entry and every citation to it fails at once, loudly
and by name, instead of quietly following a line number onto a different entry. The cost of
that is real and intended — deleting or renaming a widely-cited entry now breaks every
citation to it in one go, which is the point, not new flakiness.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "DESIGN-TRUTH.md"

# Where citations are allowed to live. `notes/` and `learnings/` are a frozen record of what
# was read and decided at the time and are not maintained against the document.
SEARCHED = ("switchboard", "tests", "defaults", "acceptance")
SUFFIXES = (".py", ".md", ".toml")

# `DESIGN-TRUTH:` then one or more quoted keys, `+`-joined, all on one line.
CITE = re.compile(r'DESIGN-TRUTH(?:\.md)?:\s*((?:"[^"]+"\s*\+\s*)*"[^"]+")')
QUOTE = re.compile(r'"([^"]+)"')

# Short enough to be a real lead-in, long enough that a fragment cannot match by luck.
MIN_QUOTE = 24


def _flat(text: str) -> str:
    """One line, single-spaced — the document wraps where it likes and citations do too."""
    return " ".join(text.split())


def entries(lines: list[str]) -> list[str]:
    """Each entry's text, flattened. An entry starts on a `**` line and ends at a blank one."""
    out, i = [], 0
    while i < len(lines):
        if lines[i].startswith("**"):
            j = i
            while j < len(lines) and lines[j].strip():
                j += 1
            out.append(_flat(" ".join(lines[i:j])))
            i = j
        else:
            i += 1
    return out


def lead_in(entry: str) -> str:
    """The bold phrase an entry opens with — its name, and the normal thing to cite."""
    m = re.match(r"\*\*(.+?)\*\*", entry)
    return m.group(1) if m else ""


def words(text: str) -> str:
    """Emphasis markers dropped, on both sides of the comparison: a citation quotes words,
    not markdown, so a quote may run from the bold lead-in into the sentence after it, and
    may keep or drop the `**` around a phrase the document emphasises."""
    return text.replace("**", "")


def _citations():
    for top in SEARCHED:
        root = ROOT / top
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in SUFFIXES or "__pycache__" in path.parts:
                continue
            if path.resolve() == Path(__file__).resolve():
                continue  # this file's own docstring examples are prose, not citations
            for n, line in enumerate(path.read_text().splitlines(), 1):
                for m in CITE.finditer(line):
                    for q in QUOTE.finditer(m.group(1)):
                        yield path.relative_to(ROOT), n, _flat(q.group(1))


class DesignTruthCitationsTest(unittest.TestCase):
    def setUp(self):
        self.entries = entries(DOC.read_text().splitlines())
        self.lead_ins = [lead_in(e) for e in self.entries]
        self.cites = list(_citations())

    def test_there_are_citations_to_check(self):
        """Guards the guard: a regex that matches nothing passes everything."""
        self.assertGreater(len(self.cites), 10)
        self.assertGreater(len(self.entries), 10)

    def test_entry_lead_ins_are_unique(self):
        """The key space itself. Two entries opening the same way makes a citation ambiguous
        even when it matches, and it would make a short lead-in unsafe to cite at all."""
        seen = set()
        for name in self.lead_ins:
            self.assertTrue(name, "an entry has no bold lead-in to cite it by")
            self.assertTrue(name not in seen, f"two entries open with {name!r}")
            seen.add(name)

    def test_every_citation_quotes_one_entry_verbatim(self):
        for where, line_no, quoted in self.cites:
            with self.subTest(f"{where}:{line_no}"):
                exact = quoted in self.lead_ins
                quoted = words(quoted)
                self.assertTrue(
                    exact or len(quoted) >= MIN_QUOTE,
                    f"{where}:{line_no} cites {quoted!r}, which is shorter than "
                    f"{MIN_QUOTE} characters and is not an entry's lead-in — too short to "
                    f"prove it points anywhere")
                self.assertTrue(
                    any(quoted in words(e) for e in self.entries),
                    f"{where}:{line_no} cites {quoted!r}, which is not the wording of any "
                    f"single entry of DESIGN-TRUTH.md — the entry was reworded, or the "
                    f"quote runs across two entries")


if __name__ == "__main__":
    unittest.main()
