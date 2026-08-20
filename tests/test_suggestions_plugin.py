"""The `suggestions` plugin — the bar, and who may delete.

Three tests, pinning decisions rather than buying confidence. Everything the plugin shares
with `report-bug` — the filename, the captured context, the session tail, the user scope —
is `report-bug`'s code, tested in `test_shipped_plugins.py`; testing it again here would
only assert that the import worked.

What is left is what this plugin decided for itself:

1. The bar is enforced, and the refusal names the flag that is missing. This is the whole
   design: a suggestion that does not clear it is refused, never filed with empty fields.
2. All three answers reach the file. A bar nothing records is not a bar.
3. `drop` is open to both. Dropping does lose the only record that the friction was ever
   paid for; agents are trusted with that, so they can bin the stale ones they filed.

Unproven, and not provable here: that agents file good suggestions, and that anybody reads
them.

Run through `cli.main` like the other shipped-plugin tests, so the parser sb builds from
the declaration and the audience gate are part of what is being tested.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_shipped_plugins import ShippedSandbox  # noqa: E402

FLAGS = ("--friction", "sb inspect showed an empty pane for a live agent",
         "--cost", "twenty minutes and one respawned child",
         "--recurs", "third time this week; the board shows it too")


class SuggestionsTest(ShippedSandbox):

    def _dir(self) -> Path:
        return self.user_state / "plugins" / "suggestions"

    def _filed(self) -> list:
        d = self._dir()
        return sorted(d.glob("*.md")) if d.is_dir() else []

    def test_a_missing_answer_is_refused_by_name(self):
        """Each of the three, dropped in turn. Named, because an agent that is told only
        "refused" guesses, and a guessing agent files the empty-field version next."""
        for flag in ("--friction", "--cost", "--recurs"):
            with self.subTest(missing=flag):
                given = [word for name, value in zip(FLAGS[::2], FLAGS[1::2])
                         if name != flag for word in (name, value)]
                code, _, err = self.sb("plugin", "suggestions", "file",
                                       "sb inspect is unreliable", *given)
                self.assertEqual(code, 1)
                self.assertIn(f"{flag} is required", err)
                self.assertEqual(self._filed(), [])

    def test_all_three_answers_reach_the_file(self):
        r = self.data("plugin", "suggestions", "file", "sb inspect is unreliable", *FLAGS)
        (p,) = list(self._dir().glob("*.md"))
        text = p.read_text()
        self.assertEqual(r["id"], p.stem)
        self.assertIn("# sb inspect is unreliable", text)
        for heading, answer in (("## friction", FLAGS[1]),
                                ("## cost", FLAGS[3]),
                                ("## recurs", FLAGS[5])):
            self.assertIn(heading, text)
            self.assertIn(answer, text)

    def test_an_agent_can_drop(self):
        """Half of the decision: the agent that filed it can bin it."""
        self.as_agent("w1")
        r = self.data("plugin", "suggestions", "file", "sb inspect is unreliable", *FLAGS)
        self.ok("plugin", "suggestions", "drop", r["id"])
        self.assertEqual(list(self._dir().glob("*.md")), [])


class SuggestionsHumanDropTest(ShippedSandbox):
    """The other half: a human at a terminal deletes the same way."""

    def test_a_human_can_drop(self):
        d = self.user_state / "plugins" / "suggestions"
        r = self.data("plugin", "suggestions", "file", "sb inspect is unreliable", *FLAGS)
        self.ok("plugin", "suggestions", "drop", r["id"])
        self.assertEqual(list(d.glob("*.md")), [])


if __name__ == "__main__":
    unittest.main()
