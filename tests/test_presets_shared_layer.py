"""The committed preset layer — `<repo>/.switchboard-shared/`.

Three tests, and they pin the three decisions that make a repo's house rules travel:
a committed preset FILE is found, a committed BINDING is joined rather than replacing the
shipped ones, and the machine-local layer still wins over the committed one. Everything
else about preset layering is already `test_presets.py`'s, whose file this deliberately
does not touch.

Kept in a file of its own rather than appended to `test_presets.py` because another agent
owns that file while this is being written.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import presets  # noqa: E402


class SharedLayerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.shared = self.repo / ".switchboard-shared"
        (self.shared / "presets").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def shipped_all(self) -> list[str]:
        """What `defaults/presets.toml` binds to every agent — read, not repeated, so these
        tests do not fail the next time the shipped baseline changes."""
        return list(presets.bindings(Path("/nonexistent-repo"))[0])

    def test_a_committed_preset_file_is_found(self):
        """The whole point: this file is tracked, so a fresh clone has it."""
        (self.shared / "presets" / "house-rules.md").write_text("# rules\nCommit on your "
                                                                "own branch.")
        self.assertEqual(presets.resolve(["house-rules"], self.repo),
                         ["Commit on your own branch."])

    def test_a_committed_binding_joins_the_shipped_ones(self):
        """`all` here must add to `defaults/presets.toml`, not replace it — a repo writing
        down its house rules cannot be allowed to silently drop what ships."""
        (self.shared / "presets.toml").write_text('all = ["house-rules"]\n')
        self.assertEqual(presets.for_role(self.repo, "worker"),
                         [*self.shipped_all(), "house-rules"])

    def test_the_machine_local_layer_still_wins(self):
        """Same name in both: `.switchboard/` is the more specific layer and overrides the
        committed one, which is how a machine keeps a local exception to a repo rule."""
        (self.shared / "presets" / "house-rules.md").write_text("# rules\nCommitted text.")
        local = self.repo / ".switchboard" / "presets"
        local.mkdir(parents=True)
        (local / "house-rules.md").write_text("# rules\nLocal text.")
        self.assertEqual(presets.resolve(["house-rules"], self.repo), ["Local text."])


if __name__ == "__main__":
    unittest.main()
