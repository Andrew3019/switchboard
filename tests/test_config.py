"""The configuration layer: `defaults/` as the base, `.switchboard/` joined on top.

Three things are worth testing here and they are not the same thing:

  1. the MERGE RULES in isolation — tables merge, scalars replace, arrays join;
  2. the LAYERING of each real file through those rules;
  3. that nothing which is configuration has stayed behind in Python.

The third is the one that rots. A role name, a model alias or a line of prompt text can be
reintroduced into a .py file in one careless edit and nothing else will notice, so the
source itself is asserted against.
"""

from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import config  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SHIPPED = REPO / "defaults"


class MergeRuleTest(unittest.TestCase):
    """Rules 1-3, on plain dicts. No files, no repo, nothing to set up."""

    def test_merging_is_recursive(self):
        got = config.merge({"a": {"b": {"c": 1, "d": 2}}}, {"a": {"b": {"d": 9}}})
        self.assertEqual(got, {"a": {"b": {"c": 1, "d": 9}}})

    def test_arrays_join_rather_than_replace(self):
        """Rule 3, and the whole reason joining is the default: adding must not remove."""
        self.assertEqual(config.merge({"all": ["a"]}, {"all": ["b"]})["all"], ["a", "b"])

    def test_joined_arrays_keep_base_order_and_drop_duplicates(self):
        self.assertEqual(config.join(["a", "b"], ["b", "c", "a"]), ["a", "b", "c"])

    def test_reset_replaces_an_array_instead_of_joining_it(self):
        """The escape hatch. Without it, 'exactly this' is unsayable once joining wins."""
        self.assertEqual(config.join(["a", "b"], [config.RESET, "c"]), ["c"])

    def test_reset_can_empty_an_array(self):
        self.assertEqual(config.join(["a"], [config.RESET]), [])

    def test_merge_does_not_mutate_either_side(self):
        """The shipped tables are cached and merged into repeatedly; one mutation would
        leak a repo's settings into every other repo in the process."""
        base = {"a": {"l": [1]}}
        config.merge(base, {"a": {"l": [2], "n": 3}})
        self.assertEqual(base, {"a": {"l": [1]}})

class FlattenTest(unittest.TestCase):
    """Markdown on disk, one line on the wire — herdr refuses newlines in agent args."""

    def test_html_comments_are_dropped_entirely(self):
        """That is where the notes to whoever edits the file live. They must not be paid
        for on every spawn."""
        got = config.flatten("<!--\nnotes for humans\n-->\nthe actual text")
        self.assertEqual(got, "the actual text")

    def test_bullets_become_separators(self):
        self.assertIn("do this ; do that", config.flatten("- do this\n- do that"))

class FrontMatterTest(unittest.TestCase):
    def test_toml_between_fences_is_parsed_and_the_rest_is_prose(self):
        fields, body = config.front_matter('+++\nmodel = "cheap"\n+++\n\nbe brief\n')
        self.assertEqual(fields, {"model": "cheap"})
        self.assertEqual(body.strip(), "be brief")

    def test_an_unclosed_fence_is_an_error_rather_than_silently_all_prose(self):
        with self.assertRaises(config.ConfigError):
            config.front_matter('+++\nmodel = "cheap"\n\nbe brief\n')

    def test_bad_toml_in_front_matter_names_itself(self):
        with self.assertRaises(config.ConfigError):
            config.front_matter("+++\nmodel = = =\n+++\nbody")


class _Layered(unittest.TestCase):
    """A temp repo with a `.switchboard/`, over the REAL shipped defaults."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.sb = self.repo / ".switchboard"
        self.sb.mkdir()
        # Otherwise a developer's own ~/.config/switchboard/models.toml decides what a tier
        # means and this suite passes or fails per machine.
        env = mock.patch.dict(
            os.environ, {"SWITCHBOARD_MODELS_CONFIG": str(self.repo / "none.toml")})
        env.start()
        self.addCleanup(env.stop)

    def write(self, rel: str, text: str) -> Path:
        p = self.sb / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p


class ShippedDefaultsTest(_Layered):
    """`defaults/` alone has to be a complete, working configuration."""

    def test_everything_works_with_no_repo_layer_at_all(self):
        bare = Path(self.tmp.name) / "bare"
        bare.mkdir()
        self.assertTrue(config.roles(bare))
        self.assertTrue(config.protocol(bare))
        every, per_role = config.preset_bindings(bare)
        # Shipped bindings are no longer empty (§7.4), and what is in them is not this
        # test's business — what is, is that a repo with no config of its own gets exactly
        # what `defaults/presets.toml` says and nothing invented on the way.
        shipped = config.read_toml(SHIPPED / "presets.toml")
        self.assertEqual(every, tuple(shipped["all"]))
        self.assertEqual(per_role,
                         {k: tuple(v) for k, v in shipped.get("roles", {}).items()})

    def test_roles_come_from_markdown_files_not_a_python_dict(self):
        names = {f.stem for f in (SHIPPED / "roles").glob("*.md")}
        for plugin in config.plugin_enablement(None):
            names.update(f.stem for f in (SHIPPED / "plugins" / plugin / "roles").glob("*.md"))
        self.assertEqual(set(config.roles(None)), names)

    def test_every_shipped_role_has_a_tier_and_a_prompt(self):
        """No `cleanup` here on purpose. A disposition is a run-time decision — the
        orchestrator's own sweep — not a property of a kind of agent, so no role file
        carries one, and `Role` no longer has the field to put it in."""
        for name, r in config.roles(None).items():
            with self.subTest(role=name):
                self.assertTrue(r.get("model"), f"{name} names no tier")
                self.assertTrue(r.get("prompt"), f"{name} has no prompt")
                self.assertNotIn("cleanup", r, f"{name} hardcodes a disposition")

    def test_the_roles_named_in_settings_all_exist(self):
        """`sb start` names a role that must have a prompt: a typo there is an
        orchestrator that silently resolves to nothing.

        `default_role` and `fallback_role` are deliberately NOT checked. Both name
        `worker`, which ships no file — an agent delegated with no `--role` gets the
        protocol, its identity, its presets and its task, and that is the whole point of
        consolidating the roles. What they must not do is name something half-defined, so
        the assertion is that they resolve, not that a file backs them."""
        roles = config.roles(None)
        self.assertIn(config.setting("vocabulary.main_role"), roles)
        for key in ("default_role", "fallback_role"):
            with self.subTest(key=key):
                self.assertTrue(config.setting(f"vocabulary.{key}"))
        # An alias IS checked against the files, and strictly, because it is the one name
        # here whose whole purpose is to not fall through: `roles.get` uses the alias only
        # when its target exists and otherwise drops to the fallback, silently, which is the
        # exact failure the alias was added to prevent. A retired name pointing at a
        # misspelt replacement would spawn an agent that cannot delegate and say nothing.
        for old, new in config.setting("vocabulary.role_aliases").items():
            with self.subTest(alias=old):
                self.assertIn(new, roles, f"alias {old!r} points at a role with no file")

    def test_the_protocol_is_a_single_line_and_names_the_verbs(self):
        line = config.protocol(None)
        self.assertNotIn("\n", line)
        for verb in ("sb inbox", "sb tell", "sb done", "sb delegate", "sb status"):
            self.assertIn(verb, line)

    def test_the_protocols_editing_notes_do_not_reach_the_agent(self):
        """They are in an HTML comment precisely so they are free. If they start being sent
        the protocol has silently tripled in size on every spawn, forever."""
        self.assertNotIn("Notes for whoever edits", config.protocol(None))

    def test_every_spawn_prompt_placeholder_is_one_the_code_fills(self):
        """A placeholder nobody fills reaches an agent as a literal `{whatever}`, which is
        invisible until someone reads a transcript."""
        filled = {
            "spawn.identity": {"name": "a", "role": "b", "parent": "c"},
            "spawn.roles": {"roles": "worker, qa"},
            "spawn.workspace": {"workspace": "w", "path": "/p"},
            "spawn.start_task": {},
            "notify.mail": {}, "notify.child_done": {}, "notify.wait_expired": {},
            "notify.interrupt": {"text": "t"},
            "notify.preset": {"name": "n", "text": "t"},
        }
        for key, fields in filled.items():
            with self.subTest(prompt=key):
                out = config.prompt(key, repo=None, **fields)
                self.assertNotIn("{", out)

    def test_an_unfilled_placeholder_fails_loudly(self):
        with self.assertRaises(config.ConfigError):
            config.prompt("spawn.identity", repo=None, name="a")

    def test_an_unknown_prompt_names_itself(self):
        with self.assertRaises(config.ConfigError):
            config.prompt("spawn.nope", repo=None)


class RoleLayeringTest(_Layered):
    def test_a_repo_overriding_one_field_keeps_the_rest_of_the_role(self):
        """The requirement, in one test: change a tier, keep the prompt."""
        shipped = config.roles(None)["researcher"]
        self.write("roles.toml", '[researcher]\nmodel = "strong"\n')
        got = config.roles(self.repo)["researcher"]
        self.assertEqual(got["model"], "strong")
        self.assertEqual(got["prompt"], shipped["prompt"])

    def test_a_repo_can_add_a_role_of_its_own(self):
        self.write("roles.toml", '[archivist]\ncleanup = "keep"\n')
        self.assertIn("archivist", config.roles(self.repo))

    def test_a_repo_markdown_role_overrides_the_shipped_prompt(self):
        self.write("roles/researcher.md", "+++\n+++\n\nDig, then say what you found.\n")
        got = config.roles(self.repo)["researcher"]
        self.assertEqual(got["prompt"], "Dig, then say what you found.")
        self.assertEqual(got["model"], config.roles(None)["researcher"]["model"])

    def test_a_repo_markdown_role_with_no_body_keeps_the_shipped_prompt(self):
        """Front matter alone adjusts the fields. Blanking the prompt would be a surprising
        thing for a file that says nothing about it to do."""
        self.write("roles/researcher.md", '+++\ncleanup = "keep"\n+++\n')
        got = config.roles(self.repo)["researcher"]
        self.assertEqual(got["cleanup"], "keep")
        self.assertEqual(got["prompt"], config.roles(None)["researcher"]["prompt"])

    def test_the_markdown_directory_wins_over_the_toml_file(self):
        """Most specific last: a whole file about one role beats one line about it."""
        self.write("roles.toml", '[researcher]\ncleanup = "close"\n')
        self.write("roles/researcher.md", '+++\ncleanup = "keep"\n+++\n')
        self.assertEqual(config.roles(self.repo)["researcher"]["cleanup"], "keep")

    def test_a_role_that_is_not_a_table_says_so(self):
        self.write("roles.toml", 'researcher = "strong"\n')
        with self.assertRaises(config.ConfigError):
            config.roles(self.repo)

    def test_an_edit_is_picked_up_rather_than_cached_forever(self):
        self.write("roles.toml", '[researcher]\nmodel = "strong"\n')
        self.assertEqual(config.roles(self.repo)["researcher"]["model"], "strong")
        self.write("roles.toml", '[researcher]\nmodel = "cheap"\n')
        self.assertEqual(config.roles(self.repo)["researcher"]["model"], "cheap")


class PresetBindingLayeringTest(_Layered):
    def test_a_repo_binding_joins_the_shipped_ones(self):
        """The requirement: adding a binding must not wipe what was shipped."""
        with mock.patch.object(config, "defaults_dir", return_value=self._fixture()):
            self.write("presets.toml", 'all = ["mine"]\n\n[roles]\nreviewer = ["extra"]\n')
            every, per_role = config.preset_bindings(self.repo)
        self.assertEqual(every, ("shipped", "mine"))
        self.assertEqual(per_role["reviewer"], ("adversarial", "extra"))

    def test_a_repo_can_reset_a_binding_list_when_it_means_to(self):
        with mock.patch.object(config, "defaults_dir", return_value=self._fixture()):
            self.write("presets.toml", 'all = ["!reset", "mine"]\n')
            every, _ = config.preset_bindings(self.repo)
        self.assertEqual(every, ("mine",))

    def test_a_role_the_shipped_layer_never_mentions_still_works(self):
        with mock.patch.object(config, "defaults_dir", return_value=self._fixture()):
            self.write("presets.toml", '[roles]\nqa = ["verify"]\n')
            _, per_role = config.preset_bindings(self.repo)
        self.assertEqual(per_role["qa"], ("verify",))
        self.assertEqual(per_role["reviewer"], ("adversarial",))   # still there

    def _fixture(self) -> Path:
        """A stand-in `defaults/` that actually ships bindings.

        The real one ships none — deliberately, because `all` is paid on every spawn — so
        joining has to be proved against something that does, or the test proves nothing.
        """
        d = self.repo / "shipped"
        d.mkdir(exist_ok=True)
        (d / "settings.toml").write_text((SHIPPED / "settings.toml").read_text())
        (d / "presets.toml").write_text(
            'all = ["shipped"]\n\n[roles]\nreviewer = ["adversarial"]\n')
        return d


class SettingsLayeringTest(_Layered):
    def test_a_repo_overrides_one_setting_and_keeps_the_rest_of_the_table(self):
        shipped_prompt = config.setting("limits.prompt")
        self.write("settings.toml", "[limits]\ntext = 10\n")
        self.assertEqual(config.setting("limits.text", repo=self.repo), 10)
        self.assertEqual(config.setting("limits.prompt", repo=self.repo), shipped_prompt)

    def test_a_repo_cannot_move_the_directory_its_own_settings_are_read_from(self):
        """`[paths] repo_dir` is shipped-only. A file that relocates the place it is looked
        for is a file that is never read again."""
        self.write("settings.toml", '[paths]\nrepo_dir = "elsewhere"\n')
        self.assertEqual(config.repo_dir(self.repo), self.sb)

    def test_a_missing_setting_falls_back_rather_than_raising(self):
        self.assertEqual(config.setting("nope.at.all", "fallback"), "fallback")

    def test_a_broken_settings_file_names_itself(self):
        self.write("settings.toml", "[limits\ntext = 1\n")
        with self.assertRaises(config.ConfigError):
            config.settings(self.repo)

    def test_a_settings_file_predating_a_key_keeps_working_on_the_shipped_value(self):
        """What makes adding a setting safe. Every repo settings.toml on disk predates
        `display.show_archived`, and none of them may break for it — the merge is over the
        shipped table, so an absent key is not a missing key."""
        self.write("settings.toml", "[limits]\ntext = 10\n")   # no [display] at all
        self.assertIs(config.flag("display.show_archived", self.repo), False)

    def test_a_boolean_setting_written_as_a_string_is_refused_not_believed(self):
        """The one type error that would otherwise pass silently. `"false"` is a non-empty
        string, so `if value` is TRUE — a person who wrote "false" would get the opposite
        of what they asked for, with nothing anywhere to say so."""
        self.write("settings.toml", '[display]\nshow_archived = "false"\n')
        with self.assertRaises(config.ConfigError) as e:
            config.flag("display.show_archived", self.repo)
        self.assertIn("display.show_archived", str(e.exception))
        self.assertIn("true or false", str(e.exception))

class OperatorSkillLayeringTest(_Layered):
    """The dispatcher's menu is data, and a repo may add to it or replace it outright."""

    def test_the_shipped_registry_is_what_a_repo_with_no_file_gets(self):
        skills = config.operator_skills(self.repo)
        shipped = config.read_toml(SHIPPED / "operator_skills.toml")["skill"]
        self.assertEqual([(s.command, s.description) for s in skills],
                         [(s["command"], s["description"]) for s in shipped])

    def test_a_repo_entry_joins_the_shipped_ones_rather_than_replacing_them(self):
        """Rule 3, and the reason the registry is an array of tables: a repo that adds its
        own procedure must not silently lose `sb presets sb-setup`."""
        self.write("operator_skills.toml",
                   '[[skill]]\ncommand = "sb presets deploy"\ndescription = "ship it"\n')
        skills = config.operator_skills(self.repo)
        commands = [s.command for s in skills]
        self.assertIn("sb presets sb-setup", commands)      # shipped survived
        self.assertEqual(commands[-1], "sb presets deploy")  # repo's is joined on the end

    def test_a_repo_can_reset_the_registry_to_exactly_its_own(self):
        """The only way to REWORD a shipped entry, since joining dedupes by whole record.

        Written as inline tables rather than `[[skill]]`, because TOML refuses to append a
        table to an array that was already given a value — `skill = ["!reset"]` followed by
        `[[skill]]` is a parse error, so a resetting repo has no other spelling available.
        """
        self.write("operator_skills.toml",
                   'skill = ["!reset", '
                   '{command = "sb presets sb-setup", description = "set this repo up"}]\n')
        skills = config.operator_skills(self.repo)
        self.assertEqual([(s.command, s.description) for s in skills],
                         [("sb presets sb-setup", "set this repo up")])


class ProtocolLayeringTest(_Layered):
    def test_a_repo_replaces_the_protocol_wholesale(self):
        """The one file that does NOT join: a protocol assembled from two halves is a
        protocol nobody can read."""
        self.write("protocol.md", "# ours\n\nSAY LESS.\n")
        self.assertEqual(config.protocol(self.repo), "SAY LESS.")

    def test_the_override_is_flattened_like_everything_else(self):
        self.write("protocol.md", "line one\nline two\n")
        self.assertNotIn("\n", config.protocol(self.repo))


class NothingLeftInPythonTest(unittest.TestCase):
    """Requirement 4: reading the shipped defaults is HOW the code gets these.

    Asserted against the source text, because that is the only thing that catches a role
    name or a prompt line being typed back into a .py file six months from now.
    """

    # Every module that could plausibly hold one. Not a whitelist of the guilty — the point
    # is that adding a role name to ANY of these is caught.
    MODULES = ("config", "roles", "models", "broker", "cli", "presets", "plugins",
               "status", "output", "herdr", "store", "validate")

    def _literals(self, *names: str) -> dict[str, list[str]]:
        """Every string LITERAL in each module, docstrings excluded.

        The AST rather than the raw text, deliberately. Comments and docstrings are where
        the reasoning lives — `defaults/roles/reviewer.md` is worth naming in prose, and a
        test that forbids it would push the explanations out of the code. What must not
        survive is a value the program actually uses.
        """
        out: dict[str, list[str]] = {}
        for n in names or self.MODULES:
            tree = ast.parse((REPO / "switchboard" / f"{n}.py").read_text())
            docstrings = {
                id(node.body[0].value)
                for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef))
                and node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            }
            out[n] = [c.value for c in ast.walk(tree)
                      if isinstance(c, ast.Constant) and isinstance(c.value, str)
                      and id(c) not in docstrings]
        return out

    def test_no_role_name_is_a_string_literal_in_python(self):
        roles = sorted(config.roles(None))
        for mod, lits in self._literals().items():
            for role in roles:
                with self.subTest(module=mod, role=role):
                    self.assertNotIn(role, lits)

    def test_no_model_name_is_a_string_literal_in_python(self):
        """Not even in models.py — the file that resolves them. `defaults/models.toml` is
        the one place, which is what makes `sb models` the only way to see them."""
        names = sorted({t.get("model") for t in
                        (config.shipped_models().get("tiers") or {}).values()} - {None})
        for mod, lits in self._literals().items():
            for model in names:
                with self.subTest(module=mod, model=model):
                    self.assertNotIn(model, lits)

    def test_no_tier_name_is_a_string_literal_in_python(self):
        """The regression this replaces: a --model help string that listed three tiers by
        hand and went stale the moment anyone invented a fourth. Not even models.py, the
        file that resolves them, may name one — including the tier a caller who asked for
        nothing gets, which comes from `[vocabulary] default_tier`."""
        for mod, lits in self._literals().items():
            for tier in sorted(config.shipped_models().get("tiers") or {}):
                with self.subTest(module=mod, tier=tier):
                    self.assertNotIn(tier, lits)

    def test_no_prompt_text_is_quoted_in_python(self):
        """Every sentence an agent is sent lives in defaults/. Sampled by first clause, so
        rewording a file does not require rewording this test."""
        fragments = [config.protocol(None).split(".")[0]]
        for table in config.prompts(None).values():
            fragments += [t.split(".")[0].split("{")[0].strip()
                          for t in table.values() if len(t.split(".")[0]) > 12]
        for mod, lits in self._literals().items():
            blob = "\n".join(lits)
            for frag in fragments:
                with self.subTest(module=mod, fragment=frag[:40]):
                    self.assertNotIn(frag, blob)

    def test_the_tunable_numbers_come_from_settings(self):
        """Every one of these used to be a literal. If a value stops matching the file, the
        module has quietly reverted to a hardcoded one."""
        from switchboard import broker, herdr, output, status, validate
        pairs = [
            (validate.MAX_TEXT, "limits.text"),
            (validate.MAX_PROMPT, "limits.prompt"),
            (validate.MAX_AGENT_NAME, "limits.agent_name"),
            (validate.MAX_REF, "limits.ref"),
            (validate.MAX_TOKEN, "limits.token"),
            (broker.INTERRUPT_SETTLE, "timeouts.interrupt_settle"),
            (broker.INLINE_MAIL_MAX, "limits.inline_mail"),
            (broker.TEARDOWN_SETTLE, "timeouts.teardown_settle"),
            (broker.TEARDOWN_SETTLE_POLL, "timeouts.teardown_settle_poll"),
            (status.DEFAULT_EVENTS, "display.events"),
            (status.TASK_CLIP, "limits.task_clip"),
            (status.WAIT_EXCUSE_GRACE, "timeouts.wait_excuse_grace"),
            (output.DEFAULT_LINES, "display.output_lines"),
            (output.CLIP, "limits.output_clip"),
            (herdr.SPAWN_ATTEMPTS, "retries.spawn_attempts"),
            (herdr.SPAWN_TIMEOUT_MS, "timeouts.spawn_ms"),
            (herdr.MIN_VERSION, "herdr.min_version"),
        ]
        for value, key in pairs:
            with self.subTest(setting=key):
                self.assertEqual(value, config.setting(key))

    def test_inspect_shows_the_tail_the_record_asks_for(self):
        """DESIGN-TRUTH: `sb inspect` "should show more tail — like 100 lines". It had
        drifted to 40. All three readers take the one setting, so a bump anywhere else is
        a second number that can disagree with this one."""
        from switchboard import herdr, output, status
        self.assertEqual(config.setting("display.output_lines"), 100)
        self.assertEqual(status.DEFAULT_LINES, 100)
        self.assertEqual(output.DEFAULT_LINES, 100)
        self.assertEqual(herdr.READ_LINES, 100)

    def test_the_vocabulary_comes_from_settings(self):
        from switchboard import broker
        self.assertEqual(broker.HUMAN, config.setting("vocabulary.human"))
        self.assertEqual(broker.PARENT, config.setting("vocabulary.parent"))
        self.assertEqual(broker.MAIN, config.setting("vocabulary.main_role"))
        self.assertEqual(list(broker.LINKED_CONFIG), config.setting("paths.linked_config"))


class DefaultsRelocationTest(unittest.TestCase):
    """SWITCHBOARD_DEFAULTS replaces the shipped baseline wholesale."""

    def test_the_defaults_directory_can_be_pointed_elsewhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "settings.toml").write_text((SHIPPED / "settings.toml").read_text())
            (d / "roles").mkdir()
            (d / "roles" / "hermit.md").write_text('+++\nmodel = "cheap"\n+++\n\nWork alone.\n')
            with mock.patch.dict(os.environ, {config.ENV_DEFAULTS: str(d)}):
                self.assertEqual(sorted(config.roles(None)), ["hermit"])

if __name__ == "__main__":
    unittest.main()
