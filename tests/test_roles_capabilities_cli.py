"""`sb roles [name]` and `sb capabilities` — the two read-only vocabulary listings.

Both answer "what does THIS repo define?", so every assertion here reads the answer off
the modules rather than repeating it: a test that named the shipped roles or the shipped
capability strings would fail the next time either set grew, which is exactly the change
these commands exist to make visible.

Driven through `cli.main` because what is being pinned is the WIRING — parser, dispatch,
`--json` shape and the refusal — not the loaders, which `test_roles` already covers.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import broker as broker_mod, cli, roles as roles_mod, store  # noqa: E402


class ListingSandbox(unittest.TestCase):
    """A throwaway repo, run from inside it, with `sb` as the door.

    Its own repo so the store is its own (the store lives under this repo's `.git`), and
    so a `.switchboard/` layer written by a test is this test's alone.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        for c in (["git", "init", "-q", "-b", "main"],
                  ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                   "commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(c, cwd=self.repo, capture_output=True)
        self.sw = self.repo / ".switchboard"
        self.sw.mkdir()
        cwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)

    def sb(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def data(self, *argv):
        code, out, err = self.sb(*argv, "--json")
        self.assertEqual(code, 0, f"`sb {' '.join(argv)}` failed: {err}")
        return json.loads(out)


class RolesListingTest(ListingSandbox):
    def test_it_lists_the_roles_this_repo_defines(self):
        self.assertEqual(self.data("roles")["roles"],
                         sorted(roles_mod.load(self.repo)))

    def test_a_named_role_exposes_tier_template_ceiling_and_prompt(self):
        """The five fields, and only those: this is the readout a planner reads a role
        off, so the shape is the contract."""
        defined = roles_mod.load(self.repo)
        name = sorted(defined)[0]
        got = self.data("roles", name)
        self.assertEqual(sorted(got), ["capabilities", "config_ceiling", "model",
                                       "name", "prompt"])
        self.assertEqual(got["name"], name)
        self.assertEqual(got["model"], defined[name].model)
        self.assertEqual(got["capabilities"], sorted(roles_mod.template_capabilities(
            defined, name, is_top=False, repo=self.repo)))
        self.assertEqual(got["config_ceiling"],
                         roles_mod.template_ceiling(defined, name, repo=self.repo))
        self.assertEqual(got["prompt"], defined[name].prompt)

    def test_an_unknown_role_is_refused_and_names_the_alternatives(self):
        """The readout uses the action's resolver and gives an actionable refusal."""
        code, out, err = self.sb("roles", "nonesuch")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("no role 'nonesuch'", err)
        self.assertIn("sb roles", err)
        self.assertTrue(any(name in err for name in roles_mod.load(self.repo)))

    def test_a_unique_spelling_variant_shows_the_resolved_role(self):
        got = self.data("roles", "RE_VIEWER")
        self.assertEqual(got["name"], "reviewer")


class InstructionRendererTest(ListingSandbox):
    def test_it_resolves_real_bindings_and_provider_delivery_without_spawning(self):
        got = self.data("instructions", "--role", "worker", "--model", "GPT 5.6 SOL",
                        "--name", "preview", "--task", "inspect this")
        self.assertEqual(got["resolved"]["tier"], "gpt-5.6-sol")
        self.assertEqual(got["resolved"]["provider"], "codex")
        self.assertIn("AGENTS.md", got["delivery"]["standing_instructions"])
        self.assertEqual(got["task"], "inspect this")
        self.assertTrue(any(s["kind"] == "binding" for s in got["segments"]))
        self.assertTrue(got["external_boundaries"])

    def test_workspace_preview_uses_the_recorded_checkout(self):
        checkout = self.repo / "worktrees" / "api"
        checkout.mkdir(parents=True)
        db = store.connect()
        self.addCleanup(db.close)
        store.record_workspace(db, "api", str(checkout), branch="api")
        got = self.data("instructions", "--workspace", "api")
        workspace = next(s for s in got["segments"] if s["kind"] == "workspace")
        self.assertIn(str(checkout), workspace["text"])


class CapabilitiesListingTest(ListingSandbox):
    def vocabulary(self) -> list[str]:
        """What `sb grant` will accept here, asked of the broker itself.

        `roles.CAPABILITIES` is the wrong thing to assert against even though it is what
        the shipped set happens to be: the vocabulary is open (C12), so a constant here
        would pin yesterday's answer and pass while the command drifted off it.

        Neither the store nor herdr is touched by `known_capabilities` — it is three
        config reads over `self.repo` — so this stands one up with neither.
        """
        return sorted(broker_mod.Broker(None, None, repo=self.repo).known_capabilities())

    def test_it_prints_the_sorted_vocabulary(self):
        self.assertEqual(self.data("capabilities")["capabilities"], self.vocabulary())

    def test_a_capability_this_repo_mints_is_in_it(self):
        """Read off the broker's vocabulary rather than off `roles.CAPABILITIES`: a repo
        that declares a side-effect capability has added a string `sb grant` accepts, and
        a listing that named the constant would advertise a different set from the one
        that command is held to."""
        (self.sw / "settings.toml").write_text(
            '[capabilities.side_effects]\ndeploy = ["merge"]\n')
        self.assertNotIn("deploy", roles_mod.CAPABILITIES)   # not shipped: this repo's own
        self.assertEqual(self.data("capabilities")["capabilities"], self.vocabulary())
        self.assertIn("deploy", self.vocabulary())
