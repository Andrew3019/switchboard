"""Preset tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import presets  # noqa: E402


class PresetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.dir = self.repo / ".switchboard" / "presets"
        self.dir.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        (self.dir / f"{name}.md").write_text(text)

    def test_discovers_files_by_name(self):
        self.write("mine-only", "# mine-only\nBe harsh.")
        self.assertIn("mine-only", presets.available(self.repo))

    def test_a_repo_preset_replaces_the_shipped_one_of_that_name(self):
        """Layered like the rest of `defaults/`: same name, repo wins."""
        self.write("adversarial", "# adversarial\nMy own version.")
        got = presets.available(self.repo)["adversarial"]
        self.assertEqual(got, self.dir / "adversarial.md")

    def test_shipped_presets_are_available_without_any_repo_config(self):
        """The shipped `presets.toml` binds these by name; if the bodies did not ship too,
        a fresh clone would have bindings pointing at nothing."""
        got = presets.available(Path(self.tmp.name) / "nope")
        self.assertIn("adversarial", got)
        self.assertIn("own-files", got)

    def test_missing_dir_is_not_an_error(self):
        presets.available(Path(self.tmp.name) / "nope")   # no raise

    def test_resolved_prompt_has_no_newlines(self):
        """herdr rejects multi-line agent args outright, so flattening is mandatory."""
        self.write("p", "# p\nfirst line\nsecond line\n\n- a bullet\n- another\n")
        (line,) = presets.resolve(["p"], self.repo)
        self.assertNotIn("\n", line)
        self.assertIn("first line", line)

    def test_bullets_stay_separated(self):
        """Run-together bullets read as prose and lose the list entirely."""
        self.write("p", "- do this\n- do that\n")
        (line,) = presets.resolve(["p"], self.repo)
        self.assertIn("do this ; do that", line)

    def test_headings_are_dropped(self):
        self.write("p", "# p\nkeep me")
        self.assertEqual(presets.resolve(["p"], self.repo), ["keep me"])

    def test_unknown_name_is_used_verbatim(self):
        """A one-off instruction should not require creating a file."""
        self.assertEqual(presets.resolve(["be terse"], self.repo), ["be terse"])

    def test_order_is_preserved(self):
        self.write("a", "AAA"); self.write("b", "BBB")
        self.assertEqual(presets.resolve(["a", "b", "raw"], self.repo),
                         ["AAA", "BBB", "raw"])

    def test_empty_preset_contributes_nothing(self):
        self.write("blank", "# blank\n\n")
        self.assertEqual(presets.resolve(["blank"], self.repo), [])

    def test_presets_are_per_repo(self):
        """switchboard's presets have no bearing on another repo's."""
        self.write("only-here", "x")
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        self.assertEqual(presets.resolve(["only-here"], other), ["only-here"])  # verbatim


class BindingTest(unittest.TestCase):
    """Which presets apply where — separate from what a role is."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / ".switchboard").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, toml):
        (self.repo / ".switchboard" / "presets.toml").write_text(toml)

    def test_no_file_means_no_bindings(self):
        self.assertEqual(presets.for_role(self.repo, "worker"), [])

    def test_all_applies_to_every_role(self):
        self.write('all = ["own-files"]\n')
        self.assertEqual(presets.for_role(self.repo, "anything"), ["own-files"])

    def test_role_bindings_append_to_all(self):
        self.write('all = ["own-files"]\n\n[roles]\nreviewer = ["adversarial"]\n')
        self.assertEqual(presets.for_role(self.repo, "reviewer"),
                         ["own-files", "adversarial"])
        self.assertEqual(presets.for_role(self.repo, "worker"), ["own-files"])

    def test_caller_extras_append_last(self):
        self.write('all = ["own-files"]\n')
        self.assertEqual(presets.for_role(self.repo, "worker", ["evidence"]),
                         ["own-files", "evidence"])

    def test_a_caller_cannot_drop_a_repo_default(self):
        """`all` is what the repo decided every agent gets; --with adds, never replaces."""
        self.write('all = ["own-files"]\n')
        self.assertIn("own-files", presets.for_role(self.repo, "worker", ["own-files"]))
        self.assertEqual(presets.for_role(self.repo, "worker", ["own-files"]), ["own-files"])

    def test_duplicates_are_collapsed(self):
        self.write('all = ["a"]\n\n[roles]\nr = ["a", "b"]\n')
        self.assertEqual(presets.for_role(self.repo, "r", ["b"]), ["a", "b"])


class PreRenameSpellingTest(unittest.TestCase):
    """`.switchboard/plugins/` and `plugins.toml` are what every repo had before the split.

    Nothing rewrites them, so the old spelling has to keep working on its own — and has to
    stop being consulted the moment the new one appears, or a repo that has moved would
    still be picking up files it thought it had left behind.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.old = self.repo / ".switchboard" / "plugins"
        self.old.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_an_unmoved_directory_is_still_read(self):
        (self.old / "legacy.md").write_text("# legacy\nstill here")
        self.assertEqual(presets.resolve(["legacy"], self.repo), ["still here"])

    def test_an_unmoved_bindings_file_is_still_read(self):
        (self.repo / ".switchboard" / "plugins.toml").write_text('all = ["own-files"]\n')
        self.assertEqual(presets.for_role(self.repo, "worker"), ["own-files"])

    def test_the_new_spelling_wins_outright(self):
        """Not merged. A repo that has moved must not keep dragging the old directory
        along, or removing a preset from it would never take effect."""
        (self.old / "legacy.md").write_text("# legacy\nold text")
        new = self.repo / ".switchboard" / "presets"
        new.mkdir()
        (new / "other.md").write_text("# other\nnew text")
        found = presets.available(self.repo)
        self.assertIn("other", found)
        self.assertNotIn("legacy", found)

    def test_the_new_bindings_file_wins_outright(self):
        (self.repo / ".switchboard" / "plugins.toml").write_text('all = ["old"]\n')
        (self.repo / ".switchboard" / "presets.toml").write_text('all = ["new"]\n')
        self.assertEqual(presets.for_role(self.repo, "worker"), ["new"])


class RetiredVerbTest(unittest.TestCase):
    """`sb plugins` was this verb. It is a hard error for one release, then removed.

    Retired loudly rather than silently: the word now means code that runs, and a caller
    who types the old spelling has two possible destinations, so the error names both.
    """

    def test_it_names_both_replacements_and_does_not_run(self):
        import io
        from contextlib import redirect_stderr
        from switchboard import cli

        err = io.StringIO()
        with redirect_stderr(err):
            code = cli.main(["plugins"])
        self.assertEqual(code, 2)
        self.assertIn("sb presets", err.getvalue())
        self.assertIn("sb plugin list", err.getvalue())

    def test_it_answers_before_anything_touches_the_store(self):
        """A retired verb has no work to do, so it must say so wherever it is typed —
        including outside a repo, where `store.connect` would answer with something else
        entirely and teach nobody anything."""
        import io
        from contextlib import redirect_stderr
        from unittest import mock
        from switchboard import cli, store

        with mock.patch.object(store, "connect",
                               side_effect=AssertionError("must not connect")):
            with redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(["plugins"]), 2)


if __name__ == "__main__":
    unittest.main()
