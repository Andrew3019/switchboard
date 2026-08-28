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

    def test_shipped_claude_tiers_pin_concrete_ids(self):
        """Shipped Claude tiers pin concrete ids; `standard` is the one that still defers.

        The invariant is knowability: an alias silently follows whatever its class points at
        this week, so a tier left floating means nobody can say what their agents ran on.
        `standard` is the deliberate exception — it is the name for "whatever the provider
        CLI defaults to" and is useless if it pins anything.

        What this catches is a tier accidentally left on an alias, which is why the pinned
        set is asserted whole rather than tier by tier.
        """
        t = self.load()
        self.assertEqual(t.resolve("cheap").model, "claude-sonnet-5")
        self.assertEqual(t.resolve("strong").model, "claude-opus-5")
        pinned = {n for n in t.names()
                  if (t.resolve(n).model or "").startswith("claude-")}
        self.assertEqual(pinned, {"cheap", "careful", "strong", "default", "prose"})
        self.assertIsNone(t.resolve("standard").model)

    # -- what the spawn layer gets ---------------------------------------

    def test_cli_args_carry_model_and_effort(self):
        """--model and --effort are both real claude flags; see models.py for the citation."""
        self.assertEqual(
            self.load().resolve("cheap").cli_args(), ["--model", "claude-sonnet-5", "--effort", "medium"])
        self.assertEqual(
            self.load().resolve("strong").cli_args(), ["--model", "claude-opus-5", "--effort", "high"])

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

    def test_a_raw_model_id_requires_the_explicit_selector(self):
        """The escape hatch stays available without turning every typo into a model id."""
        spec = self.load().resolve("raw:claude-fable-5")
        self.assertEqual(spec.model, "claude-fable-5")
        self.assertEqual(spec.cli_args(), ["--model", "claude-fable-5"])

    def test_an_unknown_tier_is_actionable(self):
        with self.assertRaises(models.ModelConfigError) as cm:
            self.load().resolve("gpt-5.6-slo")
        self.assertIn("gpt-5.6-sol", str(cm.exception))
        self.assertIn("sb models", str(cm.exception))
        self.assertIn("raw:", str(cm.exception))

    def test_a_legacy_stored_raw_id_keeps_its_pre_migration_meaning(self):
        spec = self.load().resolve_stored("claude-fable-5")
        self.assertEqual(spec.tier, "raw:claude-fable-5")
        self.assertEqual(spec.cli_args(), ["--model", "claude-fable-5"])

    def test_case_and_punctuation_variants_resolve_when_unique(self):
        self.assertEqual(self.load().resolve("GPT 5.6 SOL").tier, "gpt-5.6-sol")

    def test_a_normalized_collision_requires_an_exact_name(self):
        self.write_repo('[tiers."one-two"]\nmodel = "sonnet"\n'
                        '[tiers.one_two]\nmodel = "opus"\n')
        with self.assertRaises(models.ModelConfigError) as cm:
            self.load().resolve("one two")
        self.assertIn("ambiguous", str(cm.exception))
        self.assertIn("one-two", str(cm.exception))
        self.assertIn("one_two", str(cm.exception))

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
        self.assertEqual(spec.model, "claude-opus-5")

    # -- provider ---------------------------------------------------------

    def test_default_provider_is_configurable(self):
        self.write_repo('[defaults]\nprovider = "codex"\n[tiers.mine]\nmodel = "o9"\n')
        self.assertEqual(self.load().resolve("mine").provider, "codex")

    def test_an_unwired_provider_fails_with_a_clear_message(self):
        """A provider is a valid thing to write down; having a backend is a separate fact.

        `codex` used to be the example here and is now wired, so the test names one that
        is not. The rule is what is being pinned, not the membership of the list.
        """
        self.write_repo('[tiers.mine]\nprovider = "gemini"\nmodel = "o9"\n')
        spec = self.load().resolve("mine")
        self.assertEqual(spec.provider, "gemini")
        with self.assertRaises(models.ModelConfigError) as cm:
            spec.cli_args()
        self.assertIn("gemini", str(cm.exception))

    def test_a_codex_tier_emits_no_claude_flags(self):
        """The other half of the seam. `--model`/`--effort` are Claude Code's flag names
        and codex has neither — its model and effort are keys in a private per-agent
        `CODEX_HOME/config.toml` instead. Emitting them here would hand `codex` an
        argument it rejects outright; the spec carries the values to the one place that
        knows what to do with them (`Herdr._codex_args`)."""
        spec = self.load().resolve("gpt-5.5")
        self.assertEqual(spec.provider, "codex")
        self.assertEqual(spec.model, "gpt-5.5")
        self.assertEqual(spec.effort, "medium")
        self.assertEqual(spec.cli_args(), [])

    def test_both_shipped_codex_tiers_resolve_at_medium_effort(self):
        """Two slugs, both verified live against `codex debug models`, both at medium so
        that choosing between the tiers is a choice of model and not secretly of effort."""
        for tier, model in (("gpt-5.5", "gpt-5.5"), ("gpt-5.6-sol", "gpt-5.6-sol")):
            with self.subTest(tier=tier):
                spec = self.load().resolve(tier)
                self.assertEqual((spec.provider, spec.model, spec.effort),
                                 ("codex", model, "medium"))

    def test_the_deepseek_tier_points_the_same_binary_at_another_api(self):
        """`provider` is the BINARY and stays `codex` — which is what keeps the tier past
        the wired-providers gate — while `codex_provider` says which API that binary is
        pointed at. `Herdr._codex_args` hands the marker to `codex.write_home`, which is
        the only thing in the tree that knows what to do with it.

        `low`, where the two gpt tiers say `medium`, and not as a further economy:
        DeepSeek's own model catalog lists `low | high | max` for every v4 model and no
        `medium` at all, so `medium` here would name a level the model does not have."""
        spec = self.load().resolve("deepseek")
        self.assertEqual((spec.provider, spec.codex_provider), ("codex", "deepseek"))
        self.assertEqual((spec.model, spec.effort), ("deepseek-v4-flash", "low"))
        self.assertEqual(spec.cli_args(), [])   # still no claude flags: still codex

    def test_any_model_of_an_alternate_provider_is_a_tier_and_not_a_code_change(self):
        """The marker is a general field, not a shipped special case, and this is what
        that buys: a slug switchboard has never heard of is four lines in your own
        models.toml."""
        self.write_repo('[tiers.mine]\nprovider = "codex"\n'
                        'codex_provider = "deepseek"\nmodel = "deepseek-v4-pro"\n')
        spec = self.load().resolve("mine")
        self.assertEqual((spec.codex_provider, spec.model),
                         ("deepseek", "deepseek-v4-pro"))

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

    def test_a_role_can_use_the_explicit_raw_model_selector(self):
        (self.repo / ".switchboard" / "roles.toml").write_text(
            '[odd]\nmodel = "raw:claude-fable-5"\n')
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
                         ["--model", "claude-sonnet-5", "--effort", "medium"])
        # `default` pins a model but no effort, so it resolves to the one flag.
        self.assertEqual(d["tiers"]["default"]["cli_args"], ["--model", "claude-opus-5"])

    def test_models_verb_sees_repo_overrides(self):
        (self.repo / ".switchboard" / "models.toml").write_text(
            '[tiers.strong]\neffort = "max"\n')
        d = self._models_json()
        self.assertEqual(d["tiers"]["strong"]["cli_args"],
                         ["--model", "claude-opus-5", "--effort", "max"])

    def test_models_verb_reports_an_unspawnable_tier_instead_of_dying(self):
        """A provider with no backend is legal config; the listing still has to render."""
        (self.repo / ".switchboard" / "models.toml").write_text(
            '[tiers.later]\nprovider = "gemini"\nmodel = "o9"\n')
        d = self._models_json()
        self.assertEqual(d["tiers"]["later"]["cli_args"], [])
        self.assertIn("gemini", d["tiers"]["later"]["error"])
        self.assertIsNone(d["tiers"]["cheap"]["error"])   # the rest is unaffected


if __name__ == "__main__":
    unittest.main()
