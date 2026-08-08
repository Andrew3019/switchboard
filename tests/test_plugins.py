"""Prompt plugin tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import plugins  # noqa: E402


class PluginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.dir = self.repo / ".switchboard" / "plugins"
        self.dir.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        (self.dir / f"{name}.md").write_text(text)

    def test_discovers_files_by_name(self):
        self.write("mine-only", "# mine-only\nBe harsh.")
        self.assertIn("mine-only", plugins.available(self.repo))

    def test_a_repo_plugin_replaces_the_shipped_one_of_that_name(self):
        """Layered like the rest of `defaults/`: same name, repo wins."""
        self.write("adversarial", "# adversarial\nMy own version.")
        got = plugins.available(self.repo)["adversarial"]
        self.assertEqual(got, self.dir / "adversarial.md")

    def test_shipped_plugins_are_available_without_any_repo_config(self):
        """The shipped `plugins.toml` binds these by name; if the bodies did not ship too,
        a fresh clone would have bindings pointing at nothing."""
        got = plugins.available(Path(self.tmp.name) / "nope")
        self.assertIn("adversarial", got)
        self.assertIn("own-files", got)

    def test_missing_dir_is_not_an_error(self):
        plugins.available(Path(self.tmp.name) / "nope")   # no raise

    def test_resolved_prompt_has_no_newlines(self):
        """herdr rejects multi-line agent args outright, so flattening is mandatory."""
        self.write("p", "# p\nfirst line\nsecond line\n\n- a bullet\n- another\n")
        (line,) = plugins.resolve(["p"], self.repo)
        self.assertNotIn("\n", line)
        self.assertIn("first line", line)

    def test_bullets_stay_separated(self):
        """Run-together bullets read as prose and lose the list entirely."""
        self.write("p", "- do this\n- do that\n")
        (line,) = plugins.resolve(["p"], self.repo)
        self.assertIn("do this ; do that", line)

    def test_headings_are_dropped(self):
        self.write("p", "# p\nkeep me")
        self.assertEqual(plugins.resolve(["p"], self.repo), ["keep me"])

    def test_unknown_name_is_used_verbatim(self):
        """A one-off instruction should not require creating a file."""
        self.assertEqual(plugins.resolve(["be terse"], self.repo), ["be terse"])

    def test_order_is_preserved(self):
        self.write("a", "AAA"); self.write("b", "BBB")
        self.assertEqual(plugins.resolve(["a", "b", "raw"], self.repo),
                         ["AAA", "BBB", "raw"])

    def test_empty_plugin_contributes_nothing(self):
        self.write("blank", "# blank\n\n")
        self.assertEqual(plugins.resolve(["blank"], self.repo), [])

    def test_plugins_are_per_repo(self):
        """switchboard's plugins have no bearing on another repo's."""
        self.write("only-here", "x")
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        self.assertEqual(plugins.resolve(["only-here"], other), ["only-here"])  # verbatim


class BindingTest(unittest.TestCase):
    """Which plugins apply where — separate from what a role is."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / ".switchboard").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, toml):
        (self.repo / ".switchboard" / "plugins.toml").write_text(toml)

    def test_no_file_means_no_bindings(self):
        self.assertEqual(plugins.for_role(self.repo, "worker"), [])

    def test_all_applies_to_every_role(self):
        self.write('all = ["own-files"]\n')
        self.assertEqual(plugins.for_role(self.repo, "anything"), ["own-files"])

    def test_role_bindings_append_to_all(self):
        self.write('all = ["own-files"]\n\n[roles]\nreviewer = ["adversarial"]\n')
        self.assertEqual(plugins.for_role(self.repo, "reviewer"),
                         ["own-files", "adversarial"])
        self.assertEqual(plugins.for_role(self.repo, "worker"), ["own-files"])

    def test_caller_extras_append_last(self):
        self.write('all = ["own-files"]\n')
        self.assertEqual(plugins.for_role(self.repo, "worker", ["evidence"]),
                         ["own-files", "evidence"])

    def test_a_caller_cannot_drop_a_repo_default(self):
        """`all` is what the repo decided every agent gets; --with adds, never replaces."""
        self.write('all = ["own-files"]\n')
        self.assertIn("own-files", plugins.for_role(self.repo, "worker", ["own-files"]))
        self.assertEqual(plugins.for_role(self.repo, "worker", ["own-files"]), ["own-files"])

    def test_duplicates_are_collapsed(self):
        self.write('all = ["a"]\n\n[roles]\nr = ["a", "b"]\n')
        self.assertEqual(plugins.for_role(self.repo, "r", ["b"]), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
