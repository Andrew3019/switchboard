"""The citations into `DESIGN-TRUTH.md`, checked against the words they quote.

Code, prompts and tests cite the trusted document by quoting it — `DESIGN-TRUTH: "The role
list is lightly audited and fine as it is"` — because a claim about what the design says is
worth being able to open, and because the entry's own words do not move when the document is
edited. They used to be cited by line range, and the ranges rotted silently: an edit moved
every entry below it and the references kept pointing confidently at whatever now occupied
those lines. That is exactly what happened when the document was rewritten for the
dispatcher/lead split — about ten ended up on unrelated entries, and one had been wrong for
long enough that nobody could say when.

WHAT A CITATION LOOKS LIKE. The name — `DESIGN-TRUTH`, `DESIGN-TRUTH.md`, or either in the
possessive — followed by one or more double-quoted strings, joined by `+` when one point
needs two entries. A short run of prose may sit between the name and the quote, because that
is how these are actually written ("DESIGN-TRUTH rules out in as many words (...)"), and the
quote may wrap onto the next line, because comments and docstrings wrap. The normal quote is
the entry's bold lead-in, which is what makes it a pointer at an entry rather than at a
sentence; quoting a sentence from inside the entry instead is equally valid and is what about
two dozen older citations already do, deliberately, to point at the exact claim they lean on.

THE PARSER READS WHOLE FILES, NOT LINES. It used to read a line at a time, and everything
that did not open and close on that one line was skipped in silence — the possessive form and
every wrapped quote, about half of them. A skipped citation is the worst failure this file
has, because it reads as a pass. So the file is flattened first (indentation and comment
hashes dropped, blank lines and `\"\"\"` left as hard boundaries a quote may not cross), and an
opening quote that never closes before such a boundary is reported as a failure rather than
dropped.

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

# The name, in any of the four forms it is written in. Everything after it is prose until a
# quote opens.
MARK = re.compile(r"DESIGN-TRUTH(?:\.md)?(?:'s)?")
# A quoted key, and the `+` that joins a second one to it. `BREAK` is a boundary no quote may
# cross: a blank line, or a `"""` that is a docstring's edge rather than anybody's quote.
BREAK = "\x00"
QUOTE = re.compile(f'"([^"{BREAK}]+)"')
JOIN = re.compile(r'\s*\+\s*(?=")')
# Indentation and the comment hash in front of it, dropped so wrapped lines join cleanly.
INDENT = re.compile(r"^\s*(?:#+ ?)?\s*")

# How far past the name the first quote may sit. Long enough for the lead-in clauses actually
# written ("asks only that it is known", "rules out in as many words"), short enough that an
# unrelated string later in the paragraph is not swept in.
LEDE = 40

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


def flatten(text: str) -> tuple[str, list[int]]:
    """The file as one string a quote can be matched across, and the line each character came
    from. Indentation and comment hashes go, so a wrapped quote reads as the sentence it is;
    blank lines and `\"\"\"` become `BREAK`, so a quote that never closes stops there instead of
    swallowing the code below it."""
    flat, at = [], []
    for n, line in enumerate(text.splitlines(), 1):
        piece = INDENT.sub("", line).rstrip().replace('"""', BREAK) or BREAK
        flat.append(piece + " ")
        at.extend([n] * (len(piece) + 1))
    return "".join(flat), at


def parse(text: str) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Every citation in one file, as (line, quoted words), and separately every opening quote
    that runs off the end of its paragraph — reported, never dropped."""
    flat, at = flatten(text)
    found, broken = [], []
    for m in MARK.finditer(flat):
        pos = m.end()
        while True:
            edge = flat.find(BREAK, pos)
            lede = pos + LEDE if edge == -1 else min(pos + LEDE, edge)
            q = QUOTE.search(flat, pos)
            opening = flat.find('"', pos, lede)
            if opening == -1:
                break  # prose reference, or the paragraph moved on: nothing quoted
            if q is None or q.start() != opening:
                stop = flat.find(BREAK, opening)
                broken.append((at[opening], flat[opening:stop if stop != -1 else None][:60]))
                break
            found.append((at[q.start()], _flat(q.group(1))))
            j = JOIN.match(flat, q.end())
            if not j:
                break
            pos = j.end()
    return found, broken


def _files():
    for top in SEARCHED:
        root = ROOT / top
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in SUFFIXES or "__pycache__" in path.parts:
                continue
            if path.resolve() == Path(__file__).resolve():
                continue  # this file's own docstring examples are prose, not citations
            yield path


def _citations():
    for path in _files():
        found, _ = parse(path.read_text())
        for n, quoted in found:
            yield path.relative_to(ROOT), n, quoted


def _unterminated():
    for path in _files():
        _, broken = parse(path.read_text())
        for n, text in broken:
            yield path.relative_to(ROOT), n, text


class DesignTruthCitationsTest(unittest.TestCase):
    def setUp(self):
        self.entries = entries(DOC.read_text().splitlines())
        self.lead_ins = [lead_in(e) for e in self.entries]
        self.cites = list(_citations())

    def test_there_are_citations_to_check(self):
        """Guards the guard: a regex that matches nothing passes everything. The floor is set
        near the count the widened parser finds, because the failure this file is most
        vulnerable to is a narrowing that quietly stops looking at half of them."""
        self.assertGreater(len(self.cites), 40)
        self.assertGreater(len(self.entries), 10)

    def test_no_citation_is_left_half_read(self):
        """The other half of the same guard. A quote that opens next to the name and never
        closes before its paragraph ends is a citation this file cannot check — which is a
        failure to report, not a line to skip."""
        for where, line_no, text in _unterminated():
            self.fail(f"{where}:{line_no} opens a quote next to DESIGN-TRUTH that never "
                      f"closes: {text!r}")

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


class ParserTest(unittest.TestCase):
    """The two forms the line-at-a-time parser used to drop, and the one it must not start
    dropping instead."""

    def quotes(self, text):
        found, broken = parse(text)
        self.assertEqual(broken, [], "nothing here should be unterminated")
        return [q for _, q in found]

    def test_the_possessive_form_is_a_citation(self):
        """`DESIGN-TRUTH's "..."` and `DESIGN-TRUTH.md's "..."`. Only `DESIGN-TRUTH:` was
        recognised before, so every possessive citation passed unread."""
        self.assertEqual(self.quotes('# see DESIGN-TRUTH\'s "Focus as a flag" for it'),
                         ["Focus as a flag"])
        self.assertEqual(self.quotes('(DESIGN-TRUTH.md\'s "`--no-board`").'), ["`--no-board`"])

    def test_a_quote_may_wrap_and_may_follow_a_clause(self):
        """A quote that opens on one line and closes on the next is one quote, with the
        indentation and comment hash of the second line gone. A short clause between the name
        and the quote is prose, not a reason to stop looking."""
        self.assertEqual(
            self.quotes('    # DESIGN-TRUTH: "A fork that fails\n'
                        '    # refuses the spawn."\n'),
            ["A fork that fails refuses the spawn."])
        self.assertEqual(
            self.quotes('DESIGN-TRUTH rules out in as many words ("It never falls back").'),
            ["It never falls back"])

    def test_a_quote_that_never_closes_is_reported(self):
        """The widened parser reads across lines, so it must say when it has run out of
        paragraph — the silent skip is the bug being fixed, and a new one would be the same
        bug. The `+` join, and a quote belonging to somebody other than the document, are
        checked here too: they are the two ways the wider window could over-reach."""
        found, broken = parse('DESIGN-TRUTH: "A fork that fails\n\nsomething else"\n')
        self.assertEqual(found, [])
        self.assertEqual([n for n, _ in broken], [1])

        self.assertEqual(self.quotes('DESIGN-TRUTH: "Siblings are not invisible"\n'
                                     '+ "Only agents have the scope constraints."'),
                         ["Siblings are not invisible",
                          "Only agents have the scope constraints."])
        self.assertEqual(self.quotes('DESIGN-TRUTH.md: "we should detect failures"; '
                                     'Andrew: "needs to act same way as sb done"'),
                         ["we should detect failures"])


if __name__ == "__main__":
    unittest.main()
