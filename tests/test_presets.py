"""Preset tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import presets  # noqa: E402


def shipped_all() -> list[str]:
    """What `defaults/presets.toml` binds to every agent, read rather than repeated.

    Since §7.4 that list is not empty, and these tests are about the LAYERING — a repo
    appends to the shipped baseline and no caller can drop it — not about which fragments
    happen to be in the baseline this release. Reading it keeps every one of them from
    failing the next time a plugin is bound or unbound in `defaults/`. That the shipped
    entries are the *right* ones is `test_plugins.ShippedPluginTest`'s job.
    """
    return list(presets.bindings(Path("/nonexistent-repo"))[0])


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
        self.assertIn("evidence", got)

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

    def test_no_file_means_only_the_shipped_bindings(self):
        self.assertEqual(presets.for_role(self.repo, "worker"), shipped_all())

    def test_all_applies_to_every_role(self):
        self.write('all = ["own-files"]\n')
        self.assertEqual(presets.for_role(self.repo, "anything"),
                         [*shipped_all(), "own-files"])

    def test_role_bindings_append_to_all(self):
        """`wizard` deliberately: a role the shipped layer says nothing about, so what is
        asserted is this file's binding on top of `all` and nothing else. Using a role that
        also ships a binding would test two layers at once and fail whenever either moved."""
        self.write('all = ["own-files"]\n\n[roles]\nwizard = ["adversarial"]\n')
        self.assertEqual(presets.for_role(self.repo, "wizard"),
                         [*shipped_all(), "own-files", "adversarial"])
        self.assertEqual(presets.for_role(self.repo, "worker"),
                         [*shipped_all(), "own-files"])

    def test_caller_extras_append_last(self):
        self.write('all = ["own-files"]\n')
        self.assertEqual(presets.for_role(self.repo, "worker", ["evidence"]),
                         [*shipped_all(), "own-files", "evidence"])

    def test_a_caller_cannot_drop_a_repo_default(self):
        """`all` is what the repo decided every agent gets; --with adds, never replaces."""
        self.write('all = ["own-files"]\n')
        self.assertEqual(presets.for_role(self.repo, "worker", ["own-files"]),
                         [*shipped_all(), "own-files"])

    def test_a_caller_cannot_drop_a_shipped_binding_either(self):
        """The shipped layer is the same rule one layer further out, and since §7.4 it is
        the layer with something in it — so this is now testable rather than vacuous."""
        self.write('all = ["!reset", "own-files"]\n')
        self.assertEqual(presets.for_role(self.repo, "worker"), ["own-files"])

    def test_duplicates_are_collapsed(self):
        self.write('all = ["!reset", "a"]\n\n[roles]\nr = ["a", "b"]\n')
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
        self.assertEqual(presets.for_role(self.repo, "worker"),
                         [*shipped_all(), "own-files"])

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
        (self.repo / ".switchboard" / "presets.toml").write_text('all = ["!reset", "new"]\n')
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


class ReadingAPresetTest(unittest.TestCase):
    """`presets.text` — reading a preset instead of being spawned with one.

    The case that forced it: `adversarial` is a procedure an orchestrator is TOLD to run,
    so it is bound to nothing and has to be reachable by name. Before this, an unbound
    preset was unreachable except by stapling it to every spawn that might want it.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.dir = self.repo / ".switchboard" / "presets"
        self.dir.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_keeps_the_layout_and_drops_the_editor_notes(self):
        """The whole difference from `flatten`. A reader gets prose; a spawn gets one line."""
        (self.dir / "proc.md").write_text(
            "<!-- why this exists, for whoever edits it -->\n"
            "# proc\n\nFirst step.\n\n- a bullet\n- another\n")
        path, body = presets.text(self.repo, "proc")
        self.assertEqual(path, self.dir / "proc.md")
        self.assertNotIn("whoever edits", body)
        self.assertIn("# proc", body)          # heading kept — flatten drops it
        self.assertIn("\n", body)              # layout kept — flatten would not
        self.assertIn("- a bullet", body)      # still a list, not `; ` separators

    def test_an_unbound_preset_is_still_readable(self):
        """Being bound to nothing must not make a preset unreachable — that is the point."""
        (self.dir / "unbound.md").write_text("# unbound\nRun the rounds.")
        every, per_role = presets.bindings(self.repo)
        self.assertNotIn("unbound", every)
        self.assertFalse(any("unbound" in ps for ps in per_role.values()))
        self.assertIn("Run the rounds.", presets.text(self.repo, "unbound")[1])

    def test_an_unknown_name_raises_rather_than_returning_empty(self):
        with self.assertRaises(KeyError):
            presets.text(self.repo, "no-such-preset")

    def test_the_shipped_adversarial_procedure_is_readable_and_bound_to_nobody(self):
        """Pins the arrangement itself, not the prose: a repo with no preset directory can
        still read it, and nothing pays for it on spawn."""
        bare = Path(self.tmp.name) / "empty-repo"
        bare.mkdir()
        every, per_role = presets.bindings(bare)
        self.assertNotIn("adversarial", every)
        self.assertFalse(any("adversarial" in ps for ps in per_role.values()))
        self.assertIn("adversarial", presets.text(bare, "adversarial")[1])

    def test_the_verb_takes_an_optional_name(self):
        """`sb presets` still lists; `sb presets <name>` reaches the reading path. Pinned
        because the two share one verb and an argparse slip would break listing silently."""
        from switchboard import cli

        parser = cli.build_parser()
        self.assertIsNone(parser.parse_args(["presets"]).name)
        self.assertEqual(parser.parse_args(["presets", "adversarial"]).name, "adversarial")


if __name__ == "__main__":
    unittest.main()
