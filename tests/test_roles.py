"""Role and default-plugin layering."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import roles  # noqa: E402


class RolesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / ".switchboard").mkdir()
        # Point the global model config at nothing: tier resolution layers ~/.config over
        # the shipped defaults, so without this a developer's own models.toml decides what
        # `cheap` means here and the suite passes or fails per machine.
        env = mock.patch.dict(
            os.environ, {"SWITCHBOARD_MODELS_CONFIG": str(self.repo / "none.toml")})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, toml: str):
        (self.repo / ".switchboard" / "roles.toml").write_text(toml)

    # -- defaults --------------------------------------------------------

    def test_builtin_roles_load_without_a_file(self):
        r = roles.load(self.repo)
        self.assertIn("orchestrator", r)

    def test_roles_carry_no_plugin_config(self):
        """A role is what an agent IS; which plugins it gets lives in plugins.toml."""
        r = roles.load(self.repo)
        self.assertFalse(hasattr(r["worker"], "with_"))

    def test_repo_config_overrides_builtin_role_fields(self):
        self.write('[researcher]\nmodel = "strong"\n')
        r = roles.load(self.repo)
        self.assertEqual(r["researcher"].model, "strong")   # builtin default is "cheap"

    def test_unknown_role_inherits_worker(self):
        """Vocabulary is data: an undefined role works rather than erroring."""
        r = roles.load(self.repo)
        got = roles.get(r, "wizard")
        self.assertEqual(got.name, "wizard")
        self.assertEqual(got.cleanup, r["worker"].cleanup)

    # -- model tiers -----------------------------------------------------

    def test_tiers_resolve_to_aliases_not_pinned_ids(self):
        """A pinned id fails the day it is retired or the plan lacks access."""
        r = roles.load(self.repo)
        self.assertEqual(roles.get(r, "researcher").spec().model, "sonnet")

    def test_an_unknown_tier_passes_through_as_a_model_id(self):
        """The escape hatch: pin a specific model without inventing a tier for it."""
        self.write('[odd]\nmodel = "claude-fable-5"\n')
        r = roles.load(self.repo)
        self.assertEqual(r["odd"].spec().model, "claude-fable-5")

    def test_an_override_replaces_the_roles_tier(self):
        """`sb delegate --model <tier>` picks another tier, not another mechanism."""
        r = roles.load(self.repo)
        spec = roles.get(r, "researcher").spec("strong")     # the role's own tier is cheap
        self.assertEqual(spec.cli_args(), ["--model", "opus", "--effort", "high"])

    def test_an_empty_override_leaves_the_role_alone(self):
        """None and "" both mean "nothing was asked for", not "the default tier"."""
        r = roles.load(self.repo)
        self.assertEqual(roles.get(r, "researcher").spec("").model, "sonnet")

    def test_a_role_never_hands_out_a_bare_model_id(self):
        """model_id() is gone: it dropped effort, and every caller of it was a bug."""
        self.assertFalse(hasattr(roles.Role("worker"), "model_id"))




if __name__ == "__main__":
    unittest.main()
