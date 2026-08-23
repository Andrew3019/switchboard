"""Plugin tests — the loader, the contract, and the four isolation tests of §4.6.

The isolation tests are the acceptance criteria for the loader and they are written from
the design verbatim: a plugin that is `raise SystemExit(3)` at module scope, enabled and
bound, must cost every level-0 verb nothing, must cost the three spawn verbs nothing, must
not stop `sb plugin list` reporting the plugins that do work, and must fail by name rather
than by traceback when it is the thing you asked for.

The topology assertion throughout is `sb_plugin_*` never appearing in `sys.modules`. That
is what "delegate never imports plugin code" actually means, and it is checkable, which is
why it is checked rather than reasoned about.

A fake herdr does the spawning, the one from `test_workspace` — so these run fast and
spawn nothing.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from switchboard import cli  # noqa: E402
from switchboard import config  # noqa: E402
from switchboard import plugins  # noqa: E402
from switchboard import presets  # noqa: E402
from switchboard import store  # noqa: E402
from switchboard import validate  # noqa: E402

from test_workspace import FakeHerdr  # noqa: E402

# The canonical broken plugin, straight out of §4.6. `SystemExit` rather than an
# `Exception` on purpose: it is not caught by `except Exception`, so a loader that wraps
# the wrong thing fails these tests instead of passing them by accident.
BROKEN = "raise SystemExit(3)\n"

# A plugin that exercises the whole declared vocabulary: a positional, a repeatable
# option, a flag, a closed choice set, all three audiences, and every way a handler can
# end. Written as a string rather than shipped in `defaults/`, because phase 2 ships no
# plugins.
FIXTURE = '''"""A fixture plugin, for exercising the contract."""

import json

from switchboard.plugins import Result

API = 1
VERSION = "1.2.3"
SCOPE = "repo"
LOCK = True


def add(ctx, args):
    p = ctx.state_dir / "items.json"
    items = json.loads(p.read_text()) if p.exists() else []
    items.append({"text": args.text, "labels": args.label, "by": ctx.agent})
    p.write_text(json.dumps(items))
    return Result(human=f"added {args.text}", data=items[-1])


def ls(ctx, args):
    p = ctx.state_dir / "items.json"
    items = json.loads(p.read_text()) if p.exists() else []
    if args.state:
        items = [i for i in items if i.get("state") == args.state]
    return Result(human="\\n".join(i["text"] for i in items), data=items)


def where(ctx, args):
    return Result(human=str(ctx.state_dir), data=ctx.as_dict())


def drop(ctx, args):
    return Result(human="dropped")


def secret(ctx, args):
    return Result(human="agents only")


def boom(ctx, args):
    raise RuntimeError("the handler exploded")


def refuse(ctx, args):
    return Result(ok=False, human="nope", data={"why": "nope"}, code=7)


def wrong(ctx, args):
    return "not a Result"


def register(reg):
    reg.command("add", add, help="add an item",
                args=[reg.arg("text"), reg.arg("--label", repeat=True, help="a label"),
                      reg.arg("--quiet", flag=True)])
    reg.command("list", ls, help="list items",
                args=[reg.arg("--state", help="any word you use")])
    reg.command("where", where, help="print the state directory")
    reg.command("drop", drop, audience="human", help="delete outright")
    reg.command("secret", secret, audience="agent", help="for agents")
    reg.command("boom", boom, help="raise")
    reg.command("refuse", refuse, help="report failure")
    reg.command("wrong", wrong, help="return the wrong type")
    reg.command("pick", ls, help="a closed choice",
                args=[reg.arg("--state", choices=("open", "done"))])
'''


class Sandbox(unittest.TestCase):
    """A throwaway repo with its own copy of `defaults/`, so shipping a plugin is a write.

    The sandbox ships **no plugins and no bindings** unless a subclass sets `SHIPPED`.
    These tests are about the loader, the sigil and the CLI — not about what switchboard
    happens to ship this release — and since §7.4 flipped `todo` and `report-bug` to
    enabled-and-bound, every assertion of the form "and nothing else" would otherwise be a
    silent assertion about those two. `ShippedPluginTest` is where the shipped defaults are
    checked, deliberately in one place, so that binding a third plugin someday breaks one
    test class rather than twenty tests.
    """

    SHIPPED = False

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)

        self.defaults = root / "defaults"
        shutil.copytree(Path(__file__).resolve().parent.parent / "defaults", self.defaults)
        if not self.SHIPPED:
            self._unship()
        old = os.environ.get(config.ENV_DEFAULTS)
        os.environ[config.ENV_DEFAULTS] = str(self.defaults)
        self.addCleanup(lambda: os.environ.pop(config.ENV_DEFAULTS)
                        if old is None else os.environ.__setitem__(config.ENV_DEFAULTS, old))

        self.repo = root / "repo"
        self.repo.mkdir()
        for c in (["git", "init", "-q", "-b", "main"],
                  ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                   "commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(c, cwd=self.repo, capture_output=True)
        self.sw = self.repo / ".switchboard"
        self.sw.mkdir()

        self.addCleanup(self._forget_plugin_modules)

    def _unship(self) -> None:
        """Empty this sandbox's `defaults/` of plugins, enablement and bindings."""
        shutil.rmtree(self.defaults / "plugins", ignore_errors=True)
        (self.defaults / "plugins.toml").write_text("enabled = []\n")
        (self.defaults / "presets.toml").write_text("all = []\n\n[roles]\n")

    @staticmethod
    def _forget_plugin_modules() -> None:
        for k in [k for k in sys.modules if k.startswith(plugins._MODULE_PREFIX)]:
            del sys.modules[k]

    # -- writing fixtures ------------------------------------------------

    def ship(self, name: str, body: str, agent_md: str | None = None) -> Path:
        return self._write(self.defaults / "plugins" / name, body, agent_md)

    def local(self, name: str, body: str, agent_md: str | None = None) -> Path:
        return self._write(self.sw / "plugins" / name, body, agent_md)

    @staticmethod
    def _write(d: Path, body: str, agent_md: str | None) -> Path:
        d.mkdir(parents=True, exist_ok=True)
        (d / "__init__.py").write_text(body)
        if agent_md is not None:
            (d / "agent.md").write_text(agent_md)
        return d

    def enable(self, *names: str) -> None:
        (self.sw / "plugins.toml").write_text(
            "enabled = [" + ", ".join(f'"{n}"' for n in names) + "]\n")

    def bind(self, *names: str) -> None:
        (self.sw / "presets.toml").write_text(
            "all = [" + ", ".join(f'"{n}"' for n in names) + "]\n")

    def preset(self, name: str, text: str) -> None:
        d = self.sw / "presets"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.md").write_text(text)

    def loaded(self, name: str) -> plugins.Loaded:
        return plugins.load(self.repo, name)


class DiscoveryTest(Sandbox):
    """Level 1: glob the two roots, merge enablement. No import happens here at all."""

    def test_a_directory_with_an_init_is_a_plugin(self):
        self.ship("thing", FIXTURE)
        self.assertIn("thing", plugins.available(self.repo))

    def test_a_markdown_file_in_the_same_directory_is_not(self):
        """The transition rule: `.switchboard/plugins/` holds both spellings, and shape is
        what tells them apart. A pre-rename preset must not read as a plugin."""
        (self.sw / "plugins").mkdir()
        (self.sw / "plugins" / "adversarial.md").write_text("# adversarial\nBe harsh.")
        self.assertEqual(plugins.available(self.repo), {})

    def test_a_directory_without_an_init_is_not(self):
        (self.sw / "plugins" / "__pycache__").mkdir(parents=True)
        (self.sw / "plugins" / "__pycache__" / "x.pyc").write_text("")
        self.assertEqual(plugins.available(self.repo), {})

    def test_a_repo_plugin_replaces_the_shipped_one_of_that_name(self):
        """Whole-unit replacement, not field merge — the only rule that suits code."""
        self.ship("thing", FIXTURE)
        d = self.local("thing", FIXTURE)
        self.assertEqual(plugins.available(self.repo)["thing"], d)

    def test_no_plugin_directory_anywhere_is_not_an_error(self):
        self.assertEqual(plugins.available(self.repo), {})

    def test_discovery_imports_nothing(self):
        self.ship("thing", BROKEN)
        plugins.available(self.repo)
        self.assertEqual([k for k in sys.modules if k.startswith("sb_plugin_")], [])

    def test_enablement_joins_shipped_with_the_repos(self):
        (self.defaults / "plugins.toml").write_text('enabled = ["a"]\n')
        self.enable("b")
        self.assertEqual(plugins.enabled(self.repo), ("a", "b"))

    def test_reset_turns_everything_off(self):
        (self.defaults / "plugins.toml").write_text('enabled = ["a", "b"]\n')
        (self.sw / "plugins.toml").write_text('enabled = ["!reset"]\n')
        self.assertEqual(plugins.enabled(self.repo), ())

    def test_a_pre_rename_bindings_file_is_not_read_as_enablement(self):
        """`plugins.toml` means two things during the transition. The keys are disjoint, so
        a file holding both parses correctly as both and neither reader has to guess."""
        (self.sw / "plugins.toml").write_text(
            'all = ["own-files"]\nenabled = ["thing"]\n[roles]\nreviewer = ["adversarial"]\n')
        self.assertEqual(plugins.enabled(self.repo), ("thing",))
        every, per_role = config.preset_bindings(self.repo)
        self.assertEqual(every, ("own-files",))
        self.assertEqual(per_role["reviewer"], ("adversarial",))

    def test_bound_reads_the_sigil_out_of_the_bindings_file(self):
        self.bind("own-files", "@thing")
        self.assertEqual(plugins.bound(self.repo), {"thing": ["every agent"]})

    def test_a_bare_name_is_a_preset_not_a_plugin(self):
        self.bind("thing")
        self.assertEqual(plugins.bound(self.repo), {})

    def test_available_enabled_and_bound_are_three_separate_answers(self):
        """The split is load-bearing: you can use `sb plugin thing` without every spawned
        agent being told about it, and vice versa."""
        self.ship("thing", FIXTURE)
        self.assertIn("thing", plugins.available(self.repo))
        self.assertNotIn("thing", plugins.enabled(self.repo))
        self.assertNotIn("thing", plugins.bound(self.repo))
        self.enable("thing")
        self.assertIn("thing", plugins.enabled(self.repo))
        self.assertNotIn("thing", plugins.bound(self.repo))


class FragmentTest(Sandbox):
    """Level 2: read `<plugin>/agent.md` and flatten it. Still no import."""

    def test_the_fragment_is_the_agent_md_flattened(self):
        self.ship("thing", FIXTURE, agent_md="# thing\n- do this\n- do that\n")
        self.assertEqual(plugins.fragment(self.repo, "thing"), "do this ; do that")

    def test_a_fragment_has_no_newlines(self):
        """herdr refuses any agent argument containing one, which is the whole reason this
        goes through the same pipeline presets use rather than a new rule."""
        self.ship("thing", FIXTURE, agent_md="# thing\nfirst\nsecond\n")
        self.assertNotIn("\n", plugins.fragment(self.repo, "thing"))

    def test_no_agent_md_means_no_fragment(self):
        self.ship("thing", FIXTURE)
        self.assertIsNone(plugins.fragment(self.repo, "thing"))

    def test_reading_a_fragment_imports_nothing(self):
        """The property the whole topology rests on: a plugin that will not import still
        contributes its prompt text, because reading it never runs it."""
        self.ship("broken", BROKEN, agent_md="# broken\ntext that still works")
        self.assertEqual(plugins.fragment(self.repo, "broken"), "text that still works")
        self.assertEqual([k for k in sys.modules if k.startswith("sb_plugin_")], [])


class LoadTest(Sandbox):
    """Level 3: import, and call `register()`."""

    def test_a_working_plugin_reports_its_own_facts(self):
        self.ship("thing", FIXTURE)
        self.enable("thing")
        p = self.loaded("thing")
        self.assertEqual(p.status, "ok")
        self.assertEqual(p.version, "1.2.3")
        self.assertEqual(p.api, 1)
        self.assertEqual(p.scope, "repo")
        self.assertTrue(p.lock)
        self.assertIn("add", p.commands)

    def test_the_docstrings_first_line_is_the_help_text(self):
        """No separate SUMMARY constant: the docstring is already there, and it is one
        fewer name for an author to learn."""
        self.ship("thing", FIXTURE)
        self.assertEqual(self.loaded("thing").help,
                         "A fixture plugin, for exercising the contract.")

    def test_a_syntax_error_is_a_status_naming_the_file_and_line(self):
        self.ship("halfthing", "def register(reg)\n    pass\n")
        p = self.loaded("halfthing")
        self.assertEqual(p.status, "broken")
        self.assertIn("__init__.py:1", p.error)
        self.assertIn("SyntaxError", p.error)
        self.assertNotIn("\n", p.error)

    def test_a_system_exit_at_module_scope_is_caught(self):
        """`SystemExit` is not an `Exception`. Catching only `Exception` here is the bug
        this test exists to keep out."""
        self.ship("broken", BROKEN)
        p = self.loaded("broken")
        self.assertEqual(p.status, "broken")
        self.assertIn("SystemExit", p.error)

    def test_a_failed_import_leaves_nothing_behind_in_sys_modules(self):
        self.ship("broken", BROKEN)
        self.loaded("broken")
        self.assertNotIn("sb_plugin_broken", sys.modules)

    def test_an_unsupported_api_is_incompatible_not_broken(self):
        self.ship("shiny", 'API = 2\nVERSION = "2.0.0"\ndef register(reg): pass\n')
        p = self.loaded("shiny")
        self.assertEqual(p.status, "incompatible")
        self.assertIn("targets API 2", p.error)
        self.assertIn("supports API 1", p.error)
        self.assertEqual(p.version, "2.0.0")     # still reported: it imported fine

    def test_an_incompatible_plugin_registers_nothing(self):
        """`register` is part of the contract API 2 might have changed, so it is not called
        for a plugin sb has already decided it cannot speak to."""
        self.ship("shiny", "API = 2\ndef register(reg): raise AssertionError('called')\n")
        self.assertEqual(self.loaded("shiny").commands, {})

    def test_no_register_is_broken(self):
        self.ship("inert", "API = 1\n")
        self.assertIn("register", self.loaded("inert").error)

    def test_registering_no_commands_is_broken(self):
        self.ship("inert", "API = 1\ndef register(reg): pass\n")
        self.assertIn("no commands", self.loaded("inert").error)

    def test_a_register_that_raises_is_broken_not_fatal(self):
        self.ship("bad", "API = 1\ndef register(reg): raise ValueError('nope')\n")
        p = self.loaded("bad")
        self.assertEqual(p.status, "broken")
        self.assertIn("nope", p.error)

    def test_a_bad_scope_is_broken(self):
        self.ship("bad", 'API = 1\nSCOPE = "worktree"\ndef register(reg): pass\n')
        self.assertIn("SCOPE", self.loaded("bad").error)

    def test_a_reserved_name_is_refused(self):
        """`sb plugin list` is a verb, so a plugin cannot be called `list`."""
        self.ship("list", FIXTURE)
        self.assertIn("reserved", self.loaded("list").error)

    def test_one_broken_plugin_costs_the_others_nothing(self):
        self.ship("broken", BROKEN)
        self.ship("thing", FIXTURE)
        self.enable("thing")
        by_name = {p.name: p for p in plugins.load_all(self.repo)}
        self.assertEqual(by_name["broken"].status, "broken")
        self.assertEqual(by_name["thing"].status, "ok")

    def test_a_plugin_that_is_not_enabled_still_describes_itself(self):
        """`sb plugin list` shows a version and a status for something you have not turned
        on — that is how you decide whether to."""
        self.ship("thing", FIXTURE)
        p = self.loaded("thing")
        self.assertEqual(p.status, "not enabled")
        self.assertEqual(p.version, "1.2.3")

    def test_must_load_raises_for_a_broken_plugin(self):
        self.ship("broken", BROKEN)
        with self.assertRaises(plugins.PluginError) as cm:
            plugins.must_load(self.repo, "broken")
        self.assertIn("plugin 'broken' failed", str(cm.exception))

    def test_the_source_says_where_it_came_from(self):
        self.ship("shipped-one", FIXTURE)
        self.local("repo-one", FIXTURE)
        by_name = {p.name: p for p in plugins.load_all(self.repo)}
        self.assertEqual(by_name["shipped-one"].source, "shipped")
        self.assertEqual(by_name["repo-one"].source, "repo")


class RegistryTest(unittest.TestCase):
    """The declared vocabulary is exactly four keys, and every wrong declaration is caught
    at registration — where the author is — rather than at the call, where the caller is."""

    def setUp(self) -> None:
        self.reg = plugins.Registry()

    @staticmethod
    def _h(ctx, args):
        return plugins.Result()

    def test_a_declaration_becomes_a_command(self):
        self.reg.command("add", self._h, help="add", args=[self.reg.arg("text")])
        c = self.reg.commands["add"]
        self.assertEqual(c.audience, "both")
        self.assertEqual([a.name for a in c.args], ["text"])

    def test_the_same_command_twice_is_refused(self):
        self.reg.command("add", self._h)
        with self.assertRaises(ValueError):
            self.reg.command("add", self._h)

class BuiltParserTest(Sandbox):
    """sb builds the subparser from the declaration, so every plugin's `--help`, flag-level
    errors and `--json` look and behave like sb's own."""

    def setUp(self) -> None:
        super().setUp()
        self.ship("thing", FIXTURE)
        self.enable("thing")
        self.p = self.loaded("thing")
        self.parser = plugins.build_parser(self.p)

    def parse(self, *argv):
        return self.parser.parse_args(list(argv))

    def test_a_repeatable_option_collects(self):
        ns = self.parse("add", "x", "--label", "a", "--label", "b")
        self.assertEqual(ns.label, ["a", "b"])

    def test_choices_are_enforced(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.parse("pick", "--state", "sideways")

    def test_a_misspelled_flag_names_the_flag_that_was_typed(self):
        err = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(err):
            self.parse("add", "x", "--labl", "a")
        self.assertIn("--labl", err.getvalue())

    def test_json_is_accepted_on_every_command(self):
        self.assertTrue(self.parse("list", "--json").json)

    def test_help_is_generated_by_sb(self):
        out = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(out):
            self.parse("--help")
        self.assertIn("add an item", out.getvalue())
        self.assertIn("sb plugin thing", out.getvalue())

    def test_a_parsed_namespace_is_json_serialisable(self):
        """The escape hatch §4.4 keeps cheap: the same handler signature has to work over
        a pipe the day sb wants subprocess isolation."""
        ns = self.parse("add", "x", "--label", "a")
        json.dumps(vars(ns))


class ContextAndResultTest(unittest.TestCase):
    def test_a_context_carries_no_authority(self):
        """What is NOT in `Context` is the contract: no Broker, no store handle, no spawn
        authority. A plugin that can call `sb delegate` is a fork bomb waiting for a bad
        loop."""
        fields = set(plugins.Context.__dataclass_fields__)
        self.assertEqual(fields, {"api", "name", "state_dir", "repo", "worktree",
                                  "agent", "json"})

class StateTest(Sandbox):
    """sb owns the path and the lock. It creates the directory and never reads inside it."""

    def setUp(self) -> None:
        super().setUp()
        self.ship("thing", FIXTURE)
        self.enable("thing")
        self.p = self.loaded("thing")

    def test_repo_scope_lives_under_the_shared_git(self):
        d = plugins.state_dir(self.p, self.repo)
        self.assertEqual(d, store.store_dir(self.repo) / "plugins" / "thing")
        self.assertTrue(d.is_dir())

    def test_repo_scope_is_the_same_directory_from_every_worktree(self):
        """One repo identity, one state directory — the property `state.db` already has,
        reused rather than reinvented."""
        wt = Path(self.tmp.name) / "wt"
        subprocess.run(["git", "worktree", "add", "-q", "-b", "side", str(wt)],
                       cwd=self.repo, capture_output=True)
        self.assertEqual(plugins.state_dir(self.p, self.repo),
                         plugins.state_dir(self.p, wt))

    def test_user_scope_lives_under_the_configured_user_root(self):
        (self.sw / "settings.toml").write_text(
            f'[paths]\nuser_state = "{Path(self.tmp.name) / "userstate"}"\n')
        self.p.scope = "user"
        d = plugins.state_dir(self.p, self.repo)
        self.assertEqual(d, Path(self.tmp.name) / "userstate" / "plugins" / "thing")
        self.assertTrue(d.is_dir())

    def test_the_lock_is_taken_and_released(self):
        d = plugins.state_dir(self.p, self.repo)
        with plugins.locked(d):
            pass
        with plugins.locked(d):                      # a leaked fd would deadlock here
            pass

    def test_lock_false_takes_no_lock_and_creates_no_lockfile(self):
        d = plugins.state_dir(self.p, self.repo)
        with plugins.locked(d, want=False):
            pass
        self.assertFalse((d / ".lock").exists())

    def test_the_lock_is_per_state_directory(self):
        """Plugins never contend with each other."""
        self.ship("other", FIXTURE)
        other = plugins.load(self.repo, "other")
        a, b = plugins.state_dir(self.p, self.repo), plugins.state_dir(other, self.repo)
        self.assertNotEqual(a, b)
        with plugins.locked(a), plugins.locked(b):
            pass


class CliTest(Sandbox):
    """`sb plugin …` end to end, through `cli.main`, in a real repo."""

    def setUp(self) -> None:
        super().setUp()
        cwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)

    def run_sb(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    # -- the lister ------------------------------------------------------

    def test_list_with_nothing_installed_says_so(self):
        code, out, err = self.run_sb("plugin", "list")
        self.assertEqual(code, 0, err)
        self.assertIn("no plugins", out)

    def test_list_reports_version_status_and_binding(self):
        self.ship("thing", FIXTURE)
        self.enable("thing")
        self.bind("@thing")
        code, out, err = self.run_sb("plugin", "list")
        self.assertEqual(code, 0, err)
        self.assertIn("thing", out)
        self.assertIn("1.2.3", out)
        self.assertIn("ok", out)
        self.assertIn("@thing bound to every agent", out)

    def test_list_says_how_to_enable_something_that_is_not(self):
        self.ship("thing", FIXTURE)
        _, out, _ = self.run_sb("plugin", "list")
        self.assertIn("not enabled", out)

    # -- dispatch --------------------------------------------------------

    def test_a_handler_runs_and_prints_what_it_returned(self):
        self.ship("thing", FIXTURE)
        self.enable("thing")
        code, out, err = self.run_sb("plugin", "thing", "add", "buy milk")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "added buy milk")

    def test_json_works_without_the_plugin_implementing_it(self):
        """C13: the CLI is the API, and a `--json` that holds for eighteen verbs and maybe
        for plugin verbs is not one API surface."""
        self.ship("thing", FIXTURE)
        self.enable("thing")
        _, out, _ = self.run_sb("plugin", "thing", "add", "x", "--label", "a", "--json")
        got = json.loads(out)
        self.assertTrue(got["ok"])
        self.assertEqual(got["plugin"], "thing")
        self.assertEqual(got["command"], "add")
        self.assertEqual(got["data"]["labels"], ["a"])

    def test_state_survives_between_invocations(self):
        self.ship("thing", FIXTURE)
        self.enable("thing")
        self.run_sb("plugin", "thing", "add", "one")
        self.run_sb("plugin", "thing", "add", "two")
        _, out, _ = self.run_sb("plugin", "thing", "list")
        self.assertEqual(out.split(), ["one", "two"])

    def test_the_state_directory_is_created_before_the_handler_runs(self):
        self.ship("thing", FIXTURE)
        self.enable("thing")
        _, out, _ = self.run_sb("plugin", "thing", "where")
        self.assertTrue(Path(out.strip()).is_dir())

    def test_an_unknown_plugin_is_a_usage_error_with_a_suggestion(self):
        self.ship("thing", FIXTURE)
        self.enable("thing")
        code, _, err = self.run_sb("plugin", "thign", "list")
        self.assertEqual(code, 2)
        self.assertIn("did you mean 'thing'", err)

    def test_an_unknown_command_is_a_usage_error_with_a_suggestion(self):
        self.ship("thing", FIXTURE)
        self.enable("thing")
        code, _, err = self.run_sb("plugin", "thing", "lst")
        self.assertEqual(code, 2)
        self.assertIn("did you mean 'list'", err)

    def test_a_plugin_that_is_available_but_not_enabled_will_not_dispatch(self):
        self.ship("thing", FIXTURE)
        code, _, err = self.run_sb("plugin", "thing", "list")
        self.assertEqual(code, 2)
        self.assertIn("not enabled", err)
        self.assertIn("plugins.toml", err)

    def test_bare_sb_plugin_points_at_the_lister(self):
        code, _, err = self.run_sb("plugin")
        self.assertEqual(code, 2)
        self.assertIn("sb plugin list", err)

    def test_a_handler_reporting_failure_keeps_its_own_exit_code(self):
        self.ship("thing", FIXTURE)
        self.enable("thing")
        code, out, err = self.run_sb("plugin", "thing", "refuse")
        self.assertEqual(code, 7)
        self.assertIn("nope", err)

    def test_a_failure_is_ok_false_under_json(self):
        self.ship("thing", FIXTURE)
        self.enable("thing")
        code, out, _ = self.run_sb("plugin", "thing", "refuse", "--json")
        self.assertEqual(code, 7)
        self.assertFalse(json.loads(out)["ok"])

    def test_a_handler_returning_the_wrong_type_fails_by_name(self):
        self.ship("thing", FIXTURE)
        self.enable("thing")
        code, _, err = self.run_sb("plugin", "thing", "wrong")
        self.assertEqual(code, 1)
        self.assertIn("plugin 'thing' failed", err)

    # -- audience --------------------------------------------------------

    def test_a_human_command_is_refused_for_an_agent(self):
        """Declared once and enforced by sb, rather than re-implemented and eventually
        forgotten in every plugin (C6)."""
        self.ship("thing", FIXTURE)
        self.enable("thing")
        with mock.patch.object(cli.Broker, "whoami", lambda self: "w1"):
            code, _, err = self.run_sb("plugin", "thing", "drop")
        self.assertEqual(code, 1)
        self.assertIn("sb block", err)

    def test_an_agent_command_is_refused_for_the_human(self):
        self.ship("thing", FIXTURE)
        self.enable("thing")
        code, _, err = self.run_sb("plugin", "thing", "secret")
        self.assertEqual(code, 1)
        self.assertIn("for agents", err)

    def test_the_caller_reaches_the_handler_as_ctx_agent(self):
        self.ship("thing", FIXTURE)
        self.enable("thing")
        with mock.patch.object(cli.Broker, "whoami", lambda self: "w1"):
            _, out, _ = self.run_sb("plugin", "thing", "add", "x", "--json")
        self.assertEqual(json.loads(out)["data"]["by"], "w1")

    def test_a_human_reaches_the_handler_as_none(self):
        """`None` means a person is typing — provenance, not an agent called 'human'."""
        self.ship("thing", FIXTURE)
        self.enable("thing")
        _, out, _ = self.run_sb("plugin", "thing", "add", "x", "--json")
        self.assertIsNone(json.loads(out)["data"]["by"])

    # -- logging ---------------------------------------------------------

    def test_one_event_is_logged_per_handler_dispatch(self):
        """Plugins get no database handle; sb writes this on their behalf, so plugin
        activity shows up in `sb log` beside agent activity."""
        self.ship("thing", FIXTURE)
        self.enable("thing")
        self.run_sb("plugin", "thing", "add", "x")
        _, out, _ = self.run_sb("log", "--json")
        events = [e for e in json.loads(out)["events"] if e["kind"] == "plugin"]
        self.assertEqual(len(events), 1)
        payload = json.loads(events[0]["payload"])
        self.assertEqual(payload, {"plugin": "thing", "command": "add", "ok": True})

    def test_a_failed_handler_is_logged_as_failed(self):
        self.ship("thing", FIXTURE)
        self.enable("thing")
        self.run_sb("plugin", "thing", "boom")
        _, out, _ = self.run_sb("log", "--json")
        payload = json.loads([e for e in json.loads(out)["events"]
                              if e["kind"] == "plugin"][0]["payload"])
        self.assertFalse(payload["ok"])


class SigilTest(Sandbox):
    """§3.3's three resolution rules, at the level they are decided.

    `presets.resolve` is where a name becomes prompt text, so it is where the sigil is
    read. These call it directly; `FragmentInjectionTest` below is the same rules seen
    from a spawn.
    """

    def setUp(self) -> None:
        super().setUp()
        self.ship("todo", FIXTURE, agent_md="# todo\n- run `sb plugin todo list` first\n")

    # -- rule 1: `@name` is reserved -------------------------------------

    def test_an_enabled_plugin_with_an_agent_md_resolves_to_its_fragment(self):
        self.enable("todo")
        self.assertEqual(presets.resolve(["@todo"], self.repo),
                         ["run `sb plugin todo list` first"])

    def test_an_unknown_at_name_is_never_passed_through_verbatim(self):
        """The failure the sigil exists to make impossible: `@nope` reaching a system
        prompt as the two-character string `@nope`."""
        with self.assertRaises(validate.Invalid) as cm:
            presets.resolve(["@nope"], self.repo, explicit={"@nope"})
        self.assertIn("'@nope' names no plugin", str(cm.exception))

    def test_an_available_but_unenabled_plugin_says_how_to_enable_it(self):
        """Enabled, not merely available: injecting instructions for verbs that will not
        dispatch tells an agent to run commands it cannot."""
        with self.assertRaises(validate.Invalid) as cm:
            presets.resolve(["@todo"], self.repo, explicit={"@todo"})
        self.assertIn("not enabled", str(cm.exception))
        self.assertIn("plugins.toml", str(cm.exception))

    def test_an_enabled_plugin_with_no_agent_md_is_an_error_of_its_own(self):
        self.ship("bare", FIXTURE)
        self.enable("bare")
        with self.assertRaises(validate.Invalid) as cm:
            presets.resolve(["@bare"], self.repo, explicit={"@bare"})
        self.assertIn("no agent.md", str(cm.exception))

    def test_a_preset_file_of_the_same_name_is_not_what_at_means(self):
        """The sigil's other job: a preset and a plugin may share a name without either
        shadowing the other."""
        self.enable("todo")
        self.preset("todo", "# todo\nthe preset, not the plugin")
        self.assertEqual(presets.resolve(["@todo"], self.repo),
                         ["run `sb plugin todo list` first"])
        self.assertEqual(presets.resolve(["todo"], self.repo),
                         ["the preset, not the plugin"])

    # -- rule 2: a bare plugin name is an error --------------------------

    def test_a_bare_plugin_name_names_the_sigil(self):
        """`--with todo` shipping the one-word string "todo" into a system prompt looks
        like success and is not. Neither original proposal closed this."""
        self.enable("todo")
        with self.assertRaises(validate.Invalid) as cm:
            presets.resolve(["todo"], self.repo)
        self.assertIn("'todo' is a plugin fragment — write '@todo'", str(cm.exception))

    def test_a_preset_file_still_wins_over_the_bare_name_rule(self):
        """Rule 2 is 'matching no preset file'. A repo that had a `todo` preset before the
        plugin existed keeps getting it."""
        self.enable("todo")
        self.preset("todo", "# todo\nthe preset")
        self.assertEqual(presets.resolve(["todo"], self.repo), ["the preset"])

    def test_a_bare_name_for_a_plugin_that_is_not_enabled_is_still_literal(self):
        """Enabled is the trigger. An available-but-off plugin has not claimed the word,
        so a repo using it as an instruction keeps working."""
        self.assertEqual(presets.resolve(["todo"], self.repo), ["todo"])

    # -- rule 3: everything else is untouched ----------------------------

    def test_an_unrecognised_name_is_still_passed_through_verbatim(self):
        self.enable("todo")
        self.assertEqual(presets.resolve(["be terse"], self.repo), ["be terse"])

    def test_order_is_resolution_order_whatever_the_kinds_are(self):
        self.enable("todo")
        self.preset("p", "# p\nPPP")
        self.assertEqual(presets.resolve(["p", "@todo", "raw"], self.repo),
                         ["PPP", "run `sb plugin todo list` first", "raw"])

    # -- the asymmetry ---------------------------------------------------

    def test_an_explicit_fragment_that_fails_raises(self):
        """You asked for it by hand; dropping it silently spawns an agent missing an
        instruction you believed it had."""
        with self.assertRaises(validate.Invalid):
            presets.resolve(["@todo"], self.repo, explicit={"@todo"})

    def test_a_bound_fragment_that_fails_is_skipped_and_reported(self):
        """Delegation must not fail because somebody's plugin is half-installed."""
        seen = []
        out = presets.resolve(["@todo"], self.repo, on_event=lambda **kw: seen.append(kw))
        self.assertEqual(out, [])
        self.assertEqual(seen[0]["kind"], "fragment_skipped")
        self.assertEqual(seen[0]["plugin"], "todo")

    def test_the_default_is_binding_because_a_name_nobody_typed_is_one(self):
        """The empty default is the correct one on the merits, not merely the compatible
        one — which is why it is asserted rather than left to the call site."""
        self.assertEqual(presets.resolve(["@todo"], self.repo), [])

    def test_a_name_in_both_a_binding_and_the_command_line_is_explicit(self):
        """`for_role` de-duplicates, so it resolves once. A failure you can see beats a
        warning you cannot."""
        names = presets.for_role(self.repo, "worker", ["@todo"])
        self.assertEqual(names, ["@todo"])
        with self.assertRaises(validate.Invalid):
            presets.resolve(names, self.repo, explicit=frozenset(["@todo"]))

    def test_one_failing_fragment_does_not_stop_the_rest_of_a_binding(self):
        self.preset("p", "# p\nPPP")
        self.assertEqual(presets.resolve(["@todo", "p"], self.repo), ["PPP"])

    # -- the budget ------------------------------------------------------

    def test_an_over_budget_fragment_is_truncated_not_rejected(self):
        """A chatty plugin must not break spawning."""
        self.ship("fat", FIXTURE, agent_md="# fat\n" + ("wordy " * plugins.FRAGMENT_BUDGET))
        self.enable("fat")
        seen = []
        (line,) = presets.resolve(["@fat"], self.repo, explicit={"@fat"},
                                  on_event=lambda **kw: seen.append(kw))
        self.assertLessEqual(len(line), plugins.FRAGMENT_BUDGET)
        self.assertTrue(line.endswith("…"))
        self.assertEqual(seen[0]["kind"], "fragment_truncated")
        self.assertEqual(seen[0]["limit"], plugins.FRAGMENT_BUDGET)

    def test_truncation_lands_on_a_word_boundary(self):
        """The reader is a language model, and a severed word is noise."""
        self.assertEqual(plugins.clip("alpha beta gamma", 12), "alpha beta…")

    def test_a_single_word_longer_than_the_budget_is_still_cut(self):
        """No word boundary to land on. Cutting mid-word beats shipping nothing, and beats
        shipping 8000 characters of it."""
        self.assertEqual(plugins.clip("x" * 20, 5), "xxxx…")

    def test_the_budget_is_read_from_settings_and_not_repeated_in_python(self):
        self.assertEqual(plugins.FRAGMENT_BUDGET,
                         config.setting("limits.plugin_fragment"))


class FragmentInjectionTest(Sandbox):
    """The same rules, seen from a spawn — which is the only place they matter.

    A fragment rides the existing `with_` list in resolution order and gets no new slot:
    `--as` replaces the ROLE PROMPT and never touches `with_`, so fragments are already
    undisplaceable and a slot of their own would only move them away from where the caller
    typed them.
    """

    def setUp(self) -> None:
        super().setUp()
        self.ship("todo", FIXTURE, agent_md="# todo\n- run `sb plugin todo list` first\n")
        self.enable("todo")
        cwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)
        self.h = FakeHerdr(self.repo / "worktrees")

    def run_sb(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "Herdr", lambda **kw: self.h), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def prompts(self) -> list[str]:
        return self.h.started[-1]["prompts"]

    FRAGMENT = "run `sb plugin todo list` first"

    def test_a_bound_fragment_reaches_the_system_prompt(self):
        self.bind("@todo")
        code, _, err = self.run_sb("delegate", "do a thing", "--name", "a thing")
        self.assertEqual(code, 0, err)
        self.assertIn(self.FRAGMENT, self.prompts())

    def test_an_explicit_fragment_reaches_the_system_prompt(self):
        code, _, err = self.run_sb("delegate", "do a thing", "--name", "a thing", "--with", "@todo")
        self.assertEqual(code, 0, err)
        self.assertIn(self.FRAGMENT, self.prompts())

    def test_injecting_a_fragment_imports_no_plugin_code(self):
        """The single most important property in the design, asserted on the path that
        would lose it: the fragment went out and the plugin never ran."""
        self.bind("@todo")
        self.run_sb("delegate", "do a thing", "--name", "a thing")
        self.assertIn(self.FRAGMENT, self.prompts())
        self.assertEqual([k for k in sys.modules if k.startswith("sb_plugin_")], [])

    def test_a_fragment_rides_the_with_list_and_gets_no_new_slot(self):
        self.preset("p", "# p\nPPP")
        self.bind("p", "@todo")
        self.run_sb("delegate", "do a thing", "--name", "a thing", "--with", "extra")
        tail = self.prompts()[-3:]
        self.assertEqual(tail, ["PPP", self.FRAGMENT, "extra"])

    def test_as_does_not_displace_a_fragment(self):
        """`--as` replaces the role prompt at position 4 and never touches `with_`."""
        self.bind("@todo")
        self.run_sb("delegate", "do a thing", "--name", "a thing", "--as", "you are a duck")
        self.assertIn("you are a duck", self.prompts())
        self.assertEqual(self.prompts()[-1], self.FRAGMENT)

    def test_no_prompt_line_contains_a_newline(self):
        """herdr refuses any agent argument containing one. The fragment is flattened by
        the same `config.flatten` presets already use, so this holds without a new rule."""
        self.ship("multi", FIXTURE, agent_md="# multi\nfirst line\n\n- a\n- b\n")
        self.enable("todo", "multi")
        self.bind("@todo", "@multi")
        self.run_sb("delegate", "do a thing", "--name", "a thing")
        self.assertIn("a ; b", self.prompts()[-1])
        for p in self.prompts():
            self.assertNotIn("\n", p)

    # -- the asymmetry, at the spawn -------------------------------------

    def test_an_explicit_fragment_that_fails_stops_the_spawn(self):
        code, _, err = self.run_sb("delegate", "do a thing", "--name", "a thing", "--with", "@nope")
        self.assertNotEqual(code, 0)
        self.assertIn("@nope", err)
        self.assertEqual(self.h.started, [])

    def test_a_bound_fragment_that_fails_spawns_anyway_and_warns(self):
        self.bind("@nope")
        code, _, err = self.run_sb("delegate", "do a thing", "--name", "a thing")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.h.started), 1)
        self.assertIn("@nope", err)
        self.assertIn("skipped", err)

    def test_a_skipped_fragment_is_logged(self):
        self.bind("@nope")
        self.run_sb("delegate", "do a thing", "--name", "a thing")
        _, out, _ = self.run_sb("log", "--json")
        kinds = [e["kind"] for e in json.loads(out)["events"]]
        self.assertIn("fragment_skipped", kinds)

    def test_a_bare_plugin_name_in_a_binding_stops_the_spawn(self):
        """Not survivable, unlike an unresolvable `@name`: nothing about the machine makes
        a bare plugin name right, so skipping it would only hide a typo forever."""
        self.bind("todo")
        code, _, err = self.run_sb("delegate", "do a thing", "--name", "a thing")
        self.assertNotEqual(code, 0)
        self.assertIn("write '@todo'", err)
        self.assertEqual(self.h.started, [])

    def test_an_over_budget_fragment_still_spawns(self):
        self.ship("fat", FIXTURE, agent_md="# fat\n" + ("wordy " * plugins.FRAGMENT_BUDGET))
        self.enable("todo", "fat")
        self.bind("@fat")
        code, _, err = self.run_sb("delegate", "do a thing", "--name", "a thing")
        self.assertEqual(code, 0, err)
        self.assertLessEqual(len(self.prompts()[-1]), plugins.FRAGMENT_BUDGET)
        _, out, _ = self.run_sb("log", "--json")
        self.assertIn("fragment_truncated",
                      [e["kind"] for e in json.loads(out)["events"]])


class IsolationTest(Sandbox):
    """§4.6, stated as tests and made real. These are the acceptance criteria.

    All four run with a plugin that is `raise SystemExit(3)` at module scope, enabled in
    `plugins.toml` and bound in `presets.toml`.
    """

    def setUp(self) -> None:
        super().setUp()
        self.ship("broken", BROKEN, agent_md="# broken\nsomething an agent is told")
        self.enable("broken")
        # Bound as well as enabled, and now that the sigil resolves for real this is not a
        # formality: `@broken` names a plugin that cannot be imported, and it still has to
        # reach the prompt. That is the topology, stated as a spawn — the fragment is a
        # file read, so whether the code behind it runs is a question delegate never asks.
        self.bind("@broken")
        cwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)
        self.h = FakeHerdr(self.repo / "worktrees")

    def run_sb(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "Herdr", lambda **kw: self.h), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def assertNeverImported(self) -> None:
        self.assertEqual([k for k in sys.modules if k.startswith("sb_plugin_")], [],
                         "a verb below level 3 imported plugin code")

    # 1 ------------------------------------------------------------------

    # Every level-0 verb of §4.2, with a minimal legal argv. `--timeout 1` where a verb
    # would otherwise block: what is being tested is that it runs, not how long it waits.
    LEVEL_0 = {
        "status": [], "done": ["finished"],
        "tell": ["w1", "hi"], "inbox": [], "block": ["why"], "log": [], "cleanup": [],
        "inspect": ["w1"], "init": [],
        "restore": ["w1"], "board": [], "models": [],
        # A capability handed to an agent below the caller: one store write, no spawn and
        # no plugin code — the same level as the rest of the fleet's own bookkeeping.
        "grant": ["w1", "spawn"],
        # The reverse query: two store reads and no spawn, so it must not be able to reach
        # plugin code either.
        "who-holds": ["spawn"],
        # The collector's doorbell trigger: a flush with nothing after it.
        "flush": [],
        # Its reconciler trigger, and level 0 for the same reason: it runs unattended on a
        # timer, so it must not be able to reach plugin code.
        "reconcile": [],
        # The board's half-hourly worktree sweep, and level 0 for that same reason — it is
        # the one verb that DELETES unattended, so the set of code it can reach while
        # doing it is worth pinning here.
        "sweep": [],
    }

    def test_1_every_level_0_verb_runs_to_completion(self):
        with mock.patch("switchboard.board.main", lambda: 0):
            for verb, rest in self.LEVEL_0.items():
                with self.subTest(verb=verb):
                    code, out, err = self.run_sb(verb, *rest)
                    self.assertIn(code, (0, 1, 2), err)
                    self.assertNotIn("Traceback", err)
                    self.assertNeverImported()

    def test_1_the_level_0_list_is_the_whole_verb_set_minus_the_others(self):
        """The level table is a fixed, testable assignment. A verb added later without a
        level lands here, which is the point."""
        verbs = set(cli.build_parser()._subparsers._group_actions[0].choices)
        higher = {"presets",                            # level 1
                  "delegate", "start",                  # level 2
                  # level 2 for `delegate`'s own reason and no other: a conflicting merge
                  # spawns ONE integrator through the same call, so the same fragments have
                  # to be loadable. The git plumbing either side of that is level 0 work.
                  "merge",
                  "workspace",                          # reads and tears down; no spawn
                  "plugin", "doctor",                   # level 3
                  "plugins"}                            # retired, answers before anything
        self.assertEqual(verbs - higher, set(self.LEVEL_0))

    # 2 ------------------------------------------------------------------

    def test_2_delegate_spawns_normally(self):
        code, out, err = self.run_sb("delegate", "do a thing", "--name", "a thing")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.h.started), 1)
        self.assertNeverImported()

    def test_2_a_broken_plugins_fragment_is_still_injected(self):
        """Not "the spawn survived a broken plugin" but "the broken plugin still spoke".
        Skipping it would pass the test above and lose the property: sb was never going to
        run the code, so a `SystemExit` at module scope has no bearing on a markdown file
        sitting next to it. §11 item 4 records the same thing for an incompatible API."""
        self.run_sb("delegate", "do a thing", "--name", "a thing")
        self.assertIn("something an agent is told", self.h.started[0]["prompts"])
        self.assertNeverImported()

    def test_2_start_spawns_normally(self):
        # As a human: `sb start` is refused for agents, and this suite is run from a
        # Claude Code session, whose markers the test process inherits.
        with mock.patch.dict(os.environ):
            for var in cli._AGENT_SESSION_ENV:
                os.environ.pop(var, None)
            code, out, err = self.run_sb("start")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.h.started), 1)
        self.assertNeverImported()

    def test_2_both_spawn_verbs_are_covered(self):
        """It has to be both: testing `delegate` alone would have passed on the day
        `start` was silently getting no bindings at all. There were three until
        `sb workspace new` was deleted; nothing else spawns now."""
        covered = {n.split("_2_")[1].split("_")[0] for n in dir(self)
                   if n.startswith("test_2_") and "spawns_normally" in n}
        self.assertEqual(covered, {"delegate", "start"})

    # 3 ------------------------------------------------------------------

    def test_3_list_reports_every_other_plugin_correctly(self):
        self.ship("thing", FIXTURE)
        self.enable("broken", "thing")
        code, out, err = self.run_sb("plugin", "list")
        self.assertEqual(code, 0, err)
        rows = {line.split()[0]: line for line in out.splitlines() if line.strip()}
        self.assertIn("broken", rows["broken"])
        self.assertIn("SystemExit", rows["broken"])
        self.assertIn("1.2.3", rows["thing"])
        self.assertIn("ok", rows["thing"])
        self.assertNotIn("Traceback", out + err)

    # 4 ------------------------------------------------------------------

    def test_4_running_a_broken_plugin_fails_by_name(self):
        code, out, err = self.run_sb("plugin", "broken", "anything")
        self.assertNotEqual(code, 0)
        self.assertIn("sb: plugin 'broken' failed:", err)
        self.assertNotIn("Traceback", err)

    def test_4_sb_debug_prints_the_traceback_instead(self):
        with mock.patch.dict(os.environ, {"SB_DEBUG": "1"}):
            code, out, err = self.run_sb("plugin", "broken", "anything")
        self.assertNotEqual(code, 0)
        self.assertIn("Traceback", err)


class HelpIsStaticTest(unittest.TestCase):
    """`sb --help` must not import plugin code — §4.5's whole reason for REMAINDER."""

    def test_building_the_parser_imports_no_plugin(self):
        with mock.patch.object(plugins, "available",
                               side_effect=AssertionError("globbed at parse time")):
            cli.build_parser().format_help()

if __name__ == "__main__":
    unittest.main()
