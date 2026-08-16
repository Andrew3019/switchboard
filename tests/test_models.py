"""Tier resolution: config, layering, and the CLI flags it produces.

Every test pins `global_config` at a path inside the temp dir so a real
~/.config/switchboard/models.toml on the machine running these cannot change the result.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import cli, models, roles  # noqa: E402


class ModelsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        (self.repo / ".switchboard").mkdir(parents=True)
        self.global_cfg = self.root / "global.toml"

    def tearDown(self):
        self.tmp.cleanup()

    def load(self):
        return models.load(self.repo, global_config=self.global_cfg)

    def write_repo(self, toml: str):
        (self.repo / ".switchboard" / "models.toml").write_text(toml)

    def write_global(self, toml: str):
        self.global_cfg.write_text(toml)

    # -- shipped defaults ------------------------------------------------

    def test_works_with_no_config_at_all(self):
        """Switchboard has to spawn on a fresh checkout with an empty config dir."""
        t = self.load()
        self.assertIn("cheap", t)
        self.assertIn("default", t)
        self.assertIn("strong", t)

    def test_shipped_tiers_use_aliases_not_pinned_ids(self):
        """A pinned id fails the day the model is retired or the plan lacks access.

        `prose` is the one deliberate exception — it pins the PREVIOUS flagship for its
        output style, which no alias can name — so this asserts the rule AND that the
        exception stays a single documented one rather than a habit.
        """
        t = self.load()
        self.assertEqual(t.resolve("cheap").model, "sonnet")
        self.assertEqual(t.resolve("strong").model, "opus")
        pinned = [n for n in t.names()
                  if (t.resolve(n).model or "").startswith("claude-")]
        self.assertEqual(pinned, ["prose"])

    def test_no_shipped_tier_uses_xhigh(self):
        """Andrew, 2026-08-16, on the `deep` tier that lasted one day: "i dont want anything
        to ever use xhigh". A standing rule, so it is asserted rather than left to whoever
        next writes a tier. `xhigh` stays in `effort_levels` — that list is what the CLI
        accepts, which is a fact; this is the preference, and they are different things."""
        t = self.load()
        offenders = [n for n in t.names() if t.resolve(n).effort == "xhigh"]
        self.assertEqual(offenders, [])
        self.assertIn("xhigh", models.effort_levels())

    # -- what the spawn layer gets ---------------------------------------

    def test_cli_args_carry_model_and_effort(self):
        """--model and --effort are both real claude flags; see models.py for the citation."""
        self.assertEqual(
            self.load().resolve("cheap").cli_args(), ["--model", "sonnet", "--effort", "medium"])
        self.assertEqual(
            self.load().resolve("strong").cli_args(), ["--model", "opus", "--effort", "high"])

    def test_caller_never_branches_on_provider(self):
        """The spec answers 'what flags', not 'which provider' — that is the whole point."""
        self.write_repo('[tiers.mine]\nmodel = "sonnet"\neffort = "xhigh"\n')
        spec = self.load().resolve("mine")
        self.assertEqual(spec.provider, "claude")
        self.assertEqual(spec.cli_args(), ["--model", "sonnet", "--effort", "xhigh"])

    def test_extra_args_pass_through(self):
        self.write_repo('[tiers.mine]\nmodel = "opus"\nextra_args = ["--fallback-model", "sonnet"]\n')
        self.assertEqual(
            self.load().resolve("mine").cli_args(),
            ["--model", "opus", "--fallback-model", "sonnet"],
        )

    # -- user-invented tiers ---------------------------------------------

    def test_a_user_can_invent_a_tier_name(self):
        """Tier names are vocabulary, not a closed set (C12)."""
        self.write_repo('[tiers.midnight]\nmodel = "sonnet"\neffort = "max"\n')
        t = self.load()
        self.assertIn("midnight", t)
        self.assertEqual(t.resolve("midnight").effort, "max")

    def test_unknown_tier_passes_through_as_a_model_id(self):
        """The escape hatch: pin a model without editing config first."""
        spec = self.load().resolve("claude-fable-5")
        self.assertEqual(spec.model, "claude-fable-5")
        self.assertEqual(spec.cli_args(), ["--model", "claude-fable-5"])

    # -- layering ---------------------------------------------------------

    def test_repo_config_overrides_global_config(self):
        self.write_global('[tiers.strong]\nmodel = "sonnet"\n')
        self.write_repo('[tiers.strong]\nmodel = "opus"\n')
        self.assertEqual(self.load().resolve("strong").model, "opus")

    def test_layering_merges_per_field_not_wholesale(self):
        """Overriding one tier's effort must not wipe the model it inherited."""
        self.write_repo('[tiers.strong]\neffort = "max"\n')
        spec = self.load().resolve("strong")
        self.assertEqual(spec.effort, "max")
        self.assertEqual(spec.model, "opus")

    # -- provider ---------------------------------------------------------

    def test_default_provider_is_configurable(self):
        self.write_repo('[defaults]\nprovider = "codex"\n[tiers.mine]\nmodel = "o9"\n')
        self.assertEqual(self.load().resolve("mine").provider, "codex")

    def test_an_unwired_provider_fails_with_a_clear_message(self):
        """codex is a valid thing to write down; there is just no backend for it yet."""
        self.write_repo('[tiers.mine]\nprovider = "codex"\nmodel = "o9"\n')
        spec = self.load().resolve("mine")
        self.assertEqual(spec.provider, "codex")
        with self.assertRaises(models.ModelConfigError) as cm:
            spec.cli_args()
        self.assertIn("codex", str(cm.exception))

    # -- bad config -------------------------------------------------------

    def test_an_unknown_effort_level_is_rejected(self):
        self.write_repo('[tiers.mine]\neffort = "ludicrous"\n')
        with self.assertRaises(models.ModelConfigError) as cm:
            self.load()
        self.assertIn("ludicrous", str(cm.exception))

    def test_every_documented_effort_level_is_accepted(self):
        for level in models.EFFORT_LEVELS:
            with self.subTest(level=level):
                self.write_repo(f'[tiers.mine]\nmodel = "opus"\neffort = "{level}"\n')
                self.assertEqual(
                    self.load().resolve("mine").cli_args()[-2:], ["--effort", level])

    def test_an_unknown_key_is_rejected_rather_than_silently_ignored(self):
        self.write_repo('[tiers.mine]\nmodle = "opus"\n')
        with self.assertRaises(models.ModelConfigError):
            self.load()

    def test_malformed_toml_names_the_file(self):
        self.write_repo("[tiers.mine\n")
        with self.assertRaises(models.ModelConfigError) as cm:
            self.load()
        self.assertIn("models.toml", str(cm.exception))

class RoleModelTest(unittest.TestCase):
    """Roles name a tier and nothing more; models.py owns what that tier means."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / ".switchboard").mkdir()
        # roles.load() goes through models.load(), which layers ~/.config over the shipped
        # defaults. Pin that at a path inside the temp dir, for the reason in the module
        # docstring: a real global config must not decide what these assertions see.
        env = mock.patch.dict(
            os.environ, {"SWITCHBOARD_MODELS_CONFIG": str(self.repo / "none.toml")})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_roles_module_holds_no_model_names(self):
        src = Path(roles.__file__).read_text()
        for name in ("sonnet", "opus", "sonnet", "claude-"):
            self.assertNotIn(name, src, f"{name!r} leaked back into roles.py")

    def test_a_role_resolves_through_the_tier_table(self):
        (self.repo / ".switchboard" / "models.toml").write_text(
            '[tiers.cheap]\nmodel = "sonnet"\neffort = "medium"\n')
        r = roles.load(self.repo)
        spec = roles.get(r, "researcher").spec()      # researcher is the "cheap" tier
        self.assertEqual(spec.cli_args(), ["--model", "sonnet", "--effort", "medium"])

    def test_a_role_can_pin_a_model_id_directly(self):
        (self.repo / ".switchboard" / "roles.toml").write_text(
            '[odd]\nmodel = "claude-fable-5"\n')
        r = roles.load(self.repo)
        self.assertEqual(r["odd"].spec().model, "claude-fable-5")


class _StubBroker:
    """Just enough broker for the read-only `models` verb: where the repo is, and who."""

    def __init__(self, repo: Path):
        self.repo = repo

    def whoami(self) -> str:
        return "human"


class CliSurfaceTest(unittest.TestCase):
    """The CLI must not restate the tier set — it has to read it off the table."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / ".switchboard").mkdir()
        env = mock.patch.dict(
            os.environ, {"SWITCHBOARD_MODELS_CONFIG": str(self.repo / "none.toml")})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def _models_json(self) -> dict:
        args = argparse.Namespace(cmd="models", json=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli._dispatch(args, _StubBroker(self.repo), None, None)
        self.assertEqual(rc, 0)
        return json.loads(buf.getvalue())

    # -- --model help ----------------------------------------------------

    def test_model_help_lists_the_tiers_that_are_actually_loaded(self):
        """An invented tier has to show up in help without anyone editing cli.py."""
        (self.repo / ".switchboard" / "models.toml").write_text(
            '[tiers.midnight]\nmodel = "sonnet"\n')
        with mock.patch.object(cli.store, "worktree_root", return_value=self.repo):
            self.assertIn("midnight", cli._tier_help())

    def test_model_help_falls_back_rather_than_crashing(self):
        """`sb --help` outside a repo, or with a broken models.toml, must still print."""
        with mock.patch.object(cli.store, "worktree_root", side_effect=RuntimeError("nope")):
            help_ = cli._tier_help()
        for name in models.SHIPPED["tiers"]:
            self.assertIn(name, help_)

    def test_cli_source_hardcodes_no_tier_names(self):
        """The regression this replaces: a help string that listed three tiers by hand."""
        src = Path(cli.__file__).read_text()
        for name in ("cheap", "strong", "sonnet", "opus", "sonnet", "claude-"):
            self.assertNotIn(name, src, f"{name!r} leaked back into cli.py")

    # -- sb models -------------------------------------------------------

    def test_models_verb_reports_resolved_flags(self):
        d = self._models_json()
        self.assertEqual(d["tiers"]["cheap"]["cli_args"],
                         ["--model", "sonnet", "--effort", "medium"])
        # `default` defers to the provider CLI, so it resolves to no flags at all.
        self.assertEqual(d["tiers"]["default"]["cli_args"], [])

    def test_models_verb_sees_repo_overrides(self):
        (self.repo / ".switchboard" / "models.toml").write_text(
            '[tiers.strong]\neffort = "max"\n')
        d = self._models_json()
        self.assertEqual(d["tiers"]["strong"]["cli_args"],
                         ["--model", "opus", "--effort", "max"])

    def test_models_verb_reports_an_unspawnable_tier_instead_of_dying(self):
        """A provider with no backend is legal config; the listing still has to render."""
        (self.repo / ".switchboard" / "models.toml").write_text(
            '[tiers.later]\nprovider = "codex"\nmodel = "o9"\n')
        d = self._models_json()
        self.assertEqual(d["tiers"]["later"]["cli_args"], [])
        self.assertIn("codex", d["tiers"]["later"]["error"])
        self.assertIsNone(d["tiers"]["cheap"]["error"])   # the rest is unaffected


if __name__ == "__main__":
    unittest.main()
