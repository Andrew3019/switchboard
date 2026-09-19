"""Wave 7 #327 — presets as instructions only, prompt separation, the two-level config.

Three invariants, one class each, and each one is a property that had no test before
because the code already half-had the behaviour and nothing pinned which half:

* **INV-61** a preset is a reusable set of INSTRUCTIONS and never selects a role, a model,
  permissions, hierarchy or runtime configuration (spec §5). Structurally it could not —
  there is no field for one — so what is pinned is the one shape that looked like it could:
  TOML front matter, which is how a ROLE file declares `model = "careful"` and which a
  preset would otherwise have shipped into a system prompt as prose.
* **INV-62** role guidance, a custom agent prompt, each preset and the Task assignment stay
  conceptually separate rather than mashed into one opaque generated prompt (§5). They were
  separate in the manifest and joined with a space on the way out, which is the half that
  nobody downstream could act on.
* **INV-98/100/101** switchboard defaults → repo override → effective, resolved at spawn and
  never silently mutating a running session, validation permissive (§10). The resolution was
  there; saying WHICH LAYER an answer came from was not, and that is what a browser needs.

What no test here pins is that the labels are the right words or that the layer readout is
the right shape for a browser nobody has built yet (wave 12). Both are judgement, and the
second is deliberately left to whoever builds against it.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import config, presets, store, validate  # noqa: E402
from switchboard.broker import Broker  # noqa: E402
from switchboard.herdr import section_body  # noqa: E402

from test_workspace import FakeHerdr  # noqa: E402


class Sandbox:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.db = store.connect(path=self.repo / "state.db")
        self.h = FakeHerdr(self.repo / "worktrees")
        self.b = Broker(self.db, self.h, repo=self.repo)
        self.addCleanup(self.tmp.cleanup)

    def local(self, *parts) -> Path:
        d = self.repo.joinpath(".switchboard", *parts[:-1])
        d.mkdir(parents=True, exist_ok=True)
        return d / parts[-1]

    def spawned(self) -> list[str]:
        """The standing prompt the last spawn actually handed over, section by section."""
        return self.h.started[-1]["prompts"]


class PresetsAreInstructionsOnlyTest(Sandbox, unittest.TestCase):
    def test_a_preset_declaring_a_role_or_model_is_refused_by_name(self):
        """The only shape that could bundle one, and it fails loudly instead.

        `+++` front matter is live notation in this system — a role file declares its tier
        that way — so a preset carrying it is a plausible mistake rather than a fanciful
        one. Without the refusal `flatten` ships the raw TOML into the agent's system
        prompt as prose: it looks like it worked and it selected nothing.
        """
        p = self.local("presets", "bundled.md")
        p.write_text('+++\nrole = "reviewer"\nmodel = "strong"\n+++\n\nBe harsh.\n')
        for call in (lambda: presets.resolve(["bundled"], self.repo),
                     lambda: presets.text(self.repo, "bundled")):
            with self.assertRaises(validate.Invalid) as e:
                call()
            self.assertIn("instructions only", str(e.exception))
            # The message names BOTH fields, because a file with two of them has two
            # lines to delete and naming one sends the reader back for the other.
            self.assertIn("role", str(e.exception))
            self.assertIn("model", str(e.exception))

    def test_no_preset_this_repo_can_name_declares_anything(self):
        """The audit, as a test: every preset reachable here is prose and nothing else.

        Shipped, committed and machine-local alike — `available()` is the same three layers
        a spawn resolves through, so this fails the moment somebody adds a bundled one.
        """
        for name, path in presets.available(Path.cwd()).items():
            with self.subTest(preset=name):
                self.assertEqual(config.front_matter(path.read_text())[0], {})

    def test_the_same_preset_applies_to_any_role_on_any_model(self):
        """The consequence worth having, and the reason INV-61 is phrased as a prohibition.

        One preset, two roles, two tiers: identical text in the prompt each time, and the
        role and model the agent got are the ones the SPAWN named. A preset that selected
        either would show up here as one of them changing.
        """
        self.local("presets", "procedure.md").write_text("Run the procedure.\n")
        seen = []
        for name, role, tier in (("a", "worker", "cheap"), ("b", "reviewer", "strong")):
            m = self.b.effective_instructions(
                role=role, model=tier, name=name, with_=["procedure"])
            seen.append(next(s["text"] for s in m["segments"]
                             if s.get("binding") == "procedure"))
            self.assertEqual(m["resolved"]["role"], role)
            self.assertEqual(m["resolved"]["tier"], tier)
        self.assertEqual(seen, ["Run the procedure."] * 2)


class PromptSeparationTest(Sandbox, unittest.TestCase):
    def sections(self, manifest) -> dict[str, str]:
        """`{label: text}` for the segments that are really delivered."""
        return {s["label"]: s["text"] for s in manifest["segments"] if s["included"]}

    def test_role_custom_prompt_and_each_preset_arrive_under_their_own_heading(self):
        """The spec's diagram, as the assembled prompt (INV-62).

        Two presets and not one, because the failure this replaces was that ALL of them ran
        together: a single preset next to a role prompt would read as separated by a join
        that separated nothing.
        """
        self.local("presets", "first.md").write_text("Rule one.\n")
        self.local("presets", "second.md").write_text("Rule two.\n")
        got = self.sections(self.b.effective_instructions(
            role="worker", with_=["first", "second"]))
        self.assertEqual(got.get("ROLE GUIDANCE (worker)"),
                         next(s["text"] for s in self.b.effective_instructions(
                             role="worker")["segments"] if s["kind"] == "role-prompt"))
        self.assertEqual(got.get("PRESET first"), "Rule one.")
        self.assertEqual(got.get("PRESET second"), "Rule two.")
        # `--as` is the caller's own prompt and replaces the role's, so it takes the
        # custom-prompt heading and the role heading disappears rather than doubling.
        custom = self.sections(self.b.effective_instructions(
            role="worker", as_prompt="Do it my way.", with_=["first"]))
        self.assertEqual(custom.get("CUSTOM AGENT PROMPT"), "Do it my way.")
        self.assertNotIn("ROLE GUIDANCE (worker)", custom)
        self.assertEqual(custom.get("PRESET first"), "Rule one.")

    def test_the_assignment_is_not_in_the_standing_prompt_at_all(self):
        """The fifth column of the diagram, separated by delivery rather than by a label.

        A Task arrives as its own first user message, so the strongest form of "distinct
        from the role and the presets" is that it is not in the payload — and the manifest
        says so out loud rather than leaving a reader to notice the absence.
        """
        m = self.b.effective_instructions(role="worker", task="ship the thing")
        self.assertNotIn("ship the thing", m["rendered"])
        self.assertEqual(m["delivery"]["initial_task"], "separate first user message")
        self.assertTrue(any(b["source"] == "separately delivered initial task"
                            for b in m["external_boundaries"]))

    def test_the_live_spawn_delivers_labelled_sections_and_nothing_unlabelled(self):
        """The labels reach a real spawn, not only the renderer.

        `test_broker` pins that the preview and the spawn are ONE assembly; what this adds
        is that the shape both produce is the labelled one — every section headed, and the
        single-line rule still holding underneath with the heading as its one exemption.
        """
        self.local("presets", "first.md").write_text("Rule one.\n")
        self.b.delegate("t", topic="t", role="worker", with_=["first"])
        sections = self.spawned()
        for section in sections:
            self.assertTrue(section.startswith("## "), section[:40])
            self.assertNotIn("\n", section_body(section))
        labels = [s.partition("\n")[0] for s in sections]
        self.assertIn("## ROLE GUIDANCE (worker)", labels)
        self.assertIn("## PRESET first", labels)
        self.assertIn("## SWITCHBOARD PROTOCOL", labels)
        # One heading per section and no duplicates: a repeated label would mean two
        # segments an agent cannot tell apart, which is the failure being fixed.
        self.assertEqual(len(labels), len(set(labels)))


class TwoLevelConfigTest(Sandbox, unittest.TestCase):
    def row(self, key: str, repo=None):
        return next(r for r in config.setting_layers(repo or self.repo) if r.key == key)

    def test_a_repo_override_wins_and_says_which_layer_answered(self):
        """Default -> override -> effective, all three reported apart (§10).

        The distinction is the deliverable: a browser cannot offer "reset to default"
        without being told what the default was, and `effective` alone cannot tell a value
        somebody chose from one that was simply shipped.
        """
        bare = self.row("timeouts.stall_threshold")
        self.assertFalse(bare.overridden)
        self.assertEqual(bare.effective, bare.default)
        self.assertEqual(bare.reset(), "")

        self.local("settings.toml").write_text("[timeouts]\nstall_threshold = 42.0\n")
        row = self.row("timeouts.stall_threshold")
        self.assertTrue(row.overridden)
        self.assertEqual(row.override, 42.0)
        self.assertEqual(row.effective, 42.0)
        self.assertEqual(row.default, config.setting("timeouts.stall_threshold"))
        self.assertIn("stall_threshold", row.reset())
        # And the resolver agrees with the readout, which is what stops this being a
        # second opinion about the same file.
        self.assertEqual(config.setting("timeouts.stall_threshold", repo=self.repo), 42.0)

    def test_an_array_override_reports_the_join_rather_than_hiding_it(self):
        """Arrays JOIN (merge rule 3), so `override` and `effective` differ on purpose.

        Reporting the raw value as effective would tell a reader their list was shorter
        than it is; reporting only the effective one would hide which entry is theirs to
        delete, which is the entire content of a reset.
        """
        self.local("settings.toml").write_text('[sweep]\ndocs_dirs = ["mine"]\n')
        row = self.row("sweep.docs_dirs")
        self.assertEqual(row.override, ["mine"])
        self.assertEqual(row.effective, [*config.setting("sweep.docs_dirs"), "mine"])
        self.assertTrue(row.joined)
        self.assertIn(config.RESET, row.reset())

    def test_validation_notes_an_obviously_wrong_value_and_restricts_nothing_else(self):
        """"Validation catches obviously invalid values. Beyond that, configuration stays
        permissive" (§10). A text where a number belongs is obviously wrong in every repo;
        which role runs on which model is a COMBINATION, and a rule about it here is the
        hard-coded restriction §10 forbids."""
        self.local("settings.toml").write_text(
            '[timeouts]\nstall_threshold = "soon"\n\n[vocabulary]\ndefault_role = "reviewer"\n')
        wrong = self.row("timeouts.stall_threshold")
        self.assertIn("number", wrong.note)
        self.assertEqual(wrong.effective, "soon")      # reported, not refused
        # A role/model/preset choice is never second-guessed, however odd it looks.
        self.assertEqual(self.row("vocabulary.default_role").note, "")

    def test_a_repo_defined_role_preset_and_step_kind_resolve_in_the_same_scheme(self):
        """"Repo-defined roles, presets and step kinds are repo configuration in the same
        two-level scheme" (§10). One repo, one of each, one readout naming the layer."""
        self.local("roles", "migration-researcher.md").write_text("Read first.\n")
        self.local("presets", "architecture-critique.md").write_text("Critique it.\n")
        self.local("plans", "library", "deploy.json").write_text(
            '{"about": "ship it", "board": "deploy"}\n')
        got = {kind: {d.name: d.origin
                      for d in rows if d.origin.startswith("repo")}
               for kind, rows in config.vocabulary_layers(self.repo).items()}
        self.assertEqual(got["roles"], {"migration-researcher": "repo"})
        self.assertEqual(got["presets"], {"architecture-critique": "repo"})
        self.assertEqual(got["step-kinds"], {"deploy": "repo"})
        # And each is really nameable, not merely listed.
        self.assertIn("migration-researcher", config.roles(self.repo))
        self.assertIn("architecture-critique", presets.available(self.repo))

    def test_a_repo_step_definition_resolves_from_a_subdirectory_of_the_worktree(self):
        """The regression a review caught, pinned where it broke.

        `plans._catalogue` has no `ctx` to read the worktree off — `_lib`/`_kept` are called
        from twenty places — so it resolves one itself, and it resolved `Path.cwd()`. But the
        worktree root is `git rev-parse --show-toplevel`, so from ANY subdirectory the repo's
        layers vanished: a repo-defined kind rendered "no such definition" and
        `_kind_completion` lost its `"completion": "system"`, silently, both ways. Agents
        stand in subdirectories routinely.

        Driven on `_catalogue` directly, against a real `git init`, because the thing under
        test is which directory gets resolved — a sandbox that is not a git worktree cannot
        tell the fix from the bug.
        """
        import importlib.util
        import os
        import subprocess
        subprocess.run(["git", "init", "-q"], cwd=self.repo, capture_output=True)
        d = self.repo / ".switchboard-shared" / "plans" / "library"
        d.mkdir(parents=True)
        (d / "deploy.json").write_text('{"about": "ship it", "completion": "system"}\n')
        plugin = Path(__file__).resolve().parent.parent / "defaults" / "plugins" / "plans"
        spec = importlib.util.spec_from_file_location("plans_layers", plugin / "__init__.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        sub = self.repo / "deep" / "deeper"
        sub.mkdir(parents=True)
        cwd = Path.cwd()
        self.addCleanup(os.chdir, cwd)
        for where in (self.repo, sub):
            with self.subTest(cwd=str(where.relative_to(self.repo)) or "."):
                os.chdir(where)
                lib = mod._catalogue("library")
                self.assertIn("deploy", lib)
                self.assertEqual(lib["deploy"]["completion"], "system")
                # The shipped definitions still layer under it, so the repo layer ADDS
                # rather than replacing the catalogue.
                self.assertIn("merge", lib)

    def test_changing_repo_config_does_not_mutate_a_running_session(self):
        """"Changing repo configuration affects new agents and never silently mutates
        running sessions" (§10). Resolution is at spawn, and the proof is that the payload
        already handed over does not change under a running agent."""
        self.local("prompts.toml").write_text(
            '[spawn]\nidentity = "You are {name}, before."\n')
        Broker(self.db, self.h, repo=self.repo).delegate("t", name="w1", topic="t")
        was = list(self.spawned())
        self.assertTrue(any("before." in section for section in was))

        self.local("prompts.toml").write_text(
            '[spawn]\nidentity = "You are {name}, after."\n')
        self.assertEqual(self.spawned(), was)           # nothing was re-delivered
        self.assertEqual(len(self.h.started), 1)        # and nothing was re-spawned
        # The new value is live for the NEXT spawn, which is what makes the first half a
        # statement about timing rather than about a config read that failed.
        Broker(self.db, self.h, repo=self.repo).delegate("t", name="w2", topic="t")
        self.assertTrue(any("after." in section for section in self.spawned()))


if __name__ == "__main__":
    unittest.main()
