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

    def test_a_plugin_role_reports_the_plugin_file_as_its_source(self):
        """Effective-instruction provenance must point at the file that supplied the text,
        including roles contributed by an enabled plugin."""
        got = self.data("instructions", "--role", "planner")
        role = next(s for s in got["segments"] if s["kind"] == "role-prompt")
        self.assertTrue(role["source"].endswith(
            "defaults/plugins/plans/roles/planner.md"), role["source"])
        self.assertEqual(role["ownership"], "switchboard-owned")


    def test_the_render_carries_the_capability_seed_and_names_where_it_came_from(self):
        """§8's renderer list says "capability seed and later grants", and the manifest
        used to carry no capability field at all. Asserted against the broker's own
        `seed_for` rather than a literal bundle: the vocabulary is open (C12), so a list
        written here would pin today's shipped roles and pass while the seed drifted."""
        got = self.data("instructions", "--role", "lead")
        b = broker_mod.Broker(store.connect(), None, repo=self.repo)
        self.addCleanup(b.db.close)
        self.assertEqual(got["capabilities"]["seed"],
                         b.seed_for("lead", False, spawner="human"))
        self.assertEqual(got["capabilities"]["template"],
                         sorted(roles_mod.template_capabilities(
                             roles_mod.load(self.repo), "lead", False, self.repo)))
        self.assertTrue(got["capabilities"]["template_source"].endswith("lead.md"))
        code, out, _ = self.sb("instructions", "--role", "lead")
        self.assertEqual(code, 0)
        self.assertIn("capabilities:", out)
        for cap in got["capabilities"]["seed"]:
            self.assertIn(cap, out)
        # And the provenance follows the BUNDLE, not the prose: a repo that states a
        # role's capabilities in its own `roles.toml` must be credited for them, or the
        # manifest sends a maintainer to edit a shipped file that no longer decides it.
        (self.sw / "roles.toml").write_text(
            '[lead]\ncapabilities = ["!reset", "write-tracked"]\n')
        mine = self.data("instructions", "--role", "lead")["capabilities"]
        self.assertEqual(mine["seed"], ["write-tracked"])
        self.assertEqual(mine["template_source"], f"{self.sw / 'roles.toml'}:[lead]")
        self.assertEqual(mine["template_ownership"], "external-to-switchboard")

    def test_the_render_lists_guidance_and_lifecycle_rows_outside_the_prompt(self):
        """The other half of §8's renderer list — "relevant guidance and lifecycle state".
        The shape assertion that matters is the LAST one: these rows are delivered at the
        turn they apply to, so a render that let one into the standing payload would be
        previewing a prompt switchboard does not send."""
        got = self.data("instructions", "--role", "lead")
        kinds = {r["kind"] for r in got["just_in_time"]}
        self.assertEqual(kinds, {"guidance", "lifecycle"})
        for row in got["just_in_time"]:
            self.assertTrue(row["source"] and row["condition"] and row["resolution"])
            self.assertIn(row["ownership"],
                          {"switchboard-owned", "external-to-switchboard"})
            self.assertNotIn(row["text"], got["rendered"])
        self.assertTrue(any(r["kind"] == "guidance" for r in got["just_in_time"]))
        self.assertTrue(any(r["prompt"] == "notify.wait_expired"
                            for r in got["just_in_time"] if r["kind"] == "lifecycle"))
        code, out, _ = self.sb("instructions", "--role", "lead")
        self.assertIn("just-in-time (not in the standing prompt)", out)
        self.assertIn("notify.wait_expired", out)

    def test_a_nameless_preview_never_reads_a_live_agents_capabilities(self):
        """A bare `sb instructions --role X` must not inherit the held capabilities of an
        agent that merely happens to be named like the preview placeholder. Only an
        explicitly given `--name` previews a real live agent's caps and grants — otherwise
        the renderer would silently leak one agent's authority into an unrelated preview."""
        db = store.connect()
        self.addCleanup(db.close)
        store.create_agent(db, name="preview", role="lead", parent="human")
        store.seed_capabilities(db, "preview", ["spawn", "write-tracked"])
        # Nameless preview: the DERIVED seed, not the planted agent's caps, and not "live".
        got = self.data("instructions", "--role", "worker")["capabilities"]
        self.assertFalse(got["live"])
        self.assertEqual(got["held"], got["seed"])
        self.assertNotIn("spawn", got["held"])       # the planted agent had it; the preview must not
        self.assertEqual(got["grants"], [])
        # The live-preview feature still works when the name is asked for explicitly.
        named = self.data("instructions", "--role", "worker", "--name", "preview")["capabilities"]
        self.assertTrue(named["live"])
        self.assertEqual(named["held"], ["spawn", "write-tracked"])

    def test_a_repository_guidance_row_is_reported_against_the_file_that_added_it(self):
        """Provenance for a JOINED table. The ledger merges shipped rows with the repo's
        and a `Rule` carries no source field, so the manifest has to ask the repo file
        which ids it named — and a renderer that credited every row to
        `defaults/guidance.toml` would point a maintainer at a file they cannot edit."""
        (self.sw / "guidance.toml").write_text(
            '[[rule]]\nid = "house-rule"\ntext = "Ours."\n')
        got = self.data("instructions", "--role", "worker")
        mine = next(r for r in got["just_in_time"] if r.get("rule") == "house-rule")
        self.assertEqual(mine["source"], str(self.sw / "guidance.toml"))
        self.assertEqual(mine["ownership"], "external-to-switchboard")
        self.assertTrue(mine["included"])
        shipped = next(r for r in got["just_in_time"]
                       if r.get("rule") and r["rule"] != "house-rule")
        self.assertEqual(shipped["ownership"], "switchboard-owned")


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
