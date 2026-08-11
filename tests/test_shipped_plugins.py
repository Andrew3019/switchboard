"""The two plugins switchboard actually ships, and what `sb doctor` says about plugins.

Kept out of `test_plugins.py` on purpose. That file is about the loader — the contract, the
four isolation tests, the sigil — and its sandbox deliberately ships nothing, so that an
assertion of the form "and nothing else" stays an assertion about the fixture in front of
it. This file is the other half: `todo` and `report-bug` as they will actually be run, plus
the shipped enablement and bindings that §7.4 turned on.

Everything runs through `cli.main` rather than by calling handlers directly. A handler
called in a unit test is not what a plugin is: the parser sb builds from the declaration,
the audience refusal, the lock, the state directory and the `--json` envelope are all sb's
side of the contract, and calling `add(ctx, args)` by hand tests none of them.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from switchboard import cli  # noqa: E402
from switchboard import config  # noqa: E402
from switchboard import plugins  # noqa: E402
from switchboard import presets  # noqa: E402
from switchboard import store  # noqa: E402

from test_plugins import Sandbox  # noqa: E402


class ShippedSandbox(Sandbox):
    """A repo with the real shipped `defaults/`, run from inside, with `sb` as the door.

    `paths.user_state` is redirected into the sandbox, because `report-bug` is `SCOPE =
    "user"` and a test that files a bug into the developer's actual `~/.local/state` is a
    test that has left the sandbox.
    """

    SHIPPED = True

    def setUp(self) -> None:
        super().setUp()
        self.user_state = Path(self.tmp.name) / "userstate"
        (self.sw / "settings.toml").write_text(
            f'[paths]\nuser_state = "{self.user_state}"\n')
        cwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)

    def sb(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def ok(self, *argv) -> str:
        code, out, err = self.sb(*argv)
        self.assertEqual(code, 0, f"`sb {' '.join(argv)}` failed: {err}")
        return out

    def data(self, *argv):
        return json.loads(self.ok(*argv, "--json"))["data"]

    def as_agent(self, name: str = "w1") -> None:
        """Make this caller resolve to an agent for the rest of the test.

        Patched at `whoami` rather than by seeding a session id, because what these tests
        are about is what sb does once a caller HAS resolved to an agent; how it resolves
        is `test_broker`'s subject and is already covered there.
        """
        patch = mock.patch.object(cli.Broker, "whoami", lambda self: name)
        patch.start()
        self.addCleanup(patch.stop)


# -- what ships (§7.4) ---------------------------------------------------------


class ShippedDefaultsTest(ShippedSandbox):
    """Both plugins ship enabled AND bound, and both escape hatches still work.

    §7.4 flipped the default and kept the mechanism, which is only true if the two levers
    are still separately pullable. Testing that they are is what stops "enabled" and
    "bound" quietly collapsing into one state the next time somebody simplifies.
    """

    def test_both_plugins_are_available_out_of_the_box(self):
        self.assertEqual(sorted(plugins.available(self.repo)), ["report-bug", "todo"])

    def test_only_report_bug_ships_enabled(self):
        """`todo` is available but off. The three states are the point: it stays on disk and
        `sb plugin list` still describes it, so turning it on is one line rather than an
        install."""
        self.assertEqual(sorted(plugins.enabled(self.repo)), ["report-bug"])

    def test_only_report_bug_ships_bound_to_every_agent(self):
        self.assertEqual(plugins.bound(self.repo), {"report-bug": ["every agent"]})

    def test_every_shipped_binding_actually_resolves(self):
        """A bound name that resolves to nothing is a fragment silently missing from every
        spawn in every repo — and `all` is the worst place for it, because it is paid
        everywhere and nobody is watching any one spawn."""
        every, _ = presets.bindings(self.repo)
        self.assertTrue(every)
        for name in every:
            with self.subTest(binding=name):
                self.assertTrue(presets.resolve([name], self.repo,
                                                explicit=frozenset([name])))

    def test_every_shipped_fragment_fits_its_budget(self):
        """Written to fit the cap rather than be cut by it. A fragment that truncates on
        every spawn is one whose last sentence nobody ever reads, and the truncation event
        would be logged forever without anybody acting on it."""
        for name in plugins.enabled(self.repo):
            with self.subTest(plugin=name):
                line = plugins.fragment(self.repo, name)
                self.assertTrue(line, f"{name} ships no agent.md")
                self.assertEqual(plugins.clip(line), line,
                                 f"{name}'s fragment is {len(line)} chars, over "
                                 f"{plugins.FRAGMENT_BUDGET}")

    def test_no_shipped_fragment_tells_an_agent_to_work_from_the_list(self):
        """§9.3/§9.4. Reading a shared list and deciding what to do next is an
        orchestrator's decision, and C8 says decisions belong in a task string rather than
        diffused into every agent's system prompt."""
        line = plugins.fragment(self.repo, "todo").lower()
        for forbidden in ("claim", "pick up", "work from", "assigned to you"):
            self.assertNotIn(forbidden, line)

    def test_disabling_takes_the_commands_away(self):
        """`enabled = ["!reset"]` — off entirely. The binding is then unresolvable, and
        must be SKIPPED rather than fatal: a disabled plugin cannot stop the fleet."""
        (self.sw / "plugins.toml").write_text('enabled = ["!reset"]\n')
        self.assertEqual(plugins.enabled(self.repo), ())
        code, _, err = self.sb("plugin", "todo", "list")
        self.assertEqual(code, 2)
        self.assertIn("not enabled", err)
        self.assertEqual(presets.resolve(presets.for_role(self.repo, "builder"),
                                         self.repo), [])

# -- todo (§9) -----------------------------------------------------------------


class TodoTest(ShippedSandbox):
    """`todo` ships DISABLED, so every test here turns it on first.

    That is the point rather than an inconvenience: the plugin is complete and works, it is
    simply not something every spawn should pay for until a workflow actually uses it.
    Enabling it in one line here is the same one line a repo writes to adopt it, so these
    tests exercise the real adoption path instead of a default that happens to be on.
    """

    def setUp(self) -> None:
        super().setUp()
        (self.sw / "plugins.toml").write_text('enabled = ["todo"]\n')

    def test_an_id_is_never_reused(self):
        """A commit message citing `t-2` has to stay true for the life of the repo, so
        closing one — by either verb — must not free its number."""
        for text in ("a", "b"):
            self.ok("plugin", "todo", "add", text)
        self.ok("plugin", "todo", "done", "t-2")
        self.ok("plugin", "todo", "add", "c")
        self.assertEqual([r["id"] for r in self.data("plugin", "todo", "list", "--all")],
                         ["t-1", "t-2", "t-3"])

    def test_a_hand_edited_file_cannot_make_the_counter_go_backwards(self):
        for text in ("a", "b", "c"):
            self.ok("plugin", "todo", "add", text)
        p = self._todos()
        doc = json.loads(p.read_text())
        doc["todos"] = [r for r in doc["todos"] if r["id"] != "t-3"]
        p.write_text(json.dumps(doc))
        self.assertEqual(self.data("plugin", "todo", "add", "d")["id"], "t-4")

    def test_the_record_has_the_shape_the_design_specifies(self):
        r = self.data("plugin", "todo", "add", "a thing", "--label", "config")
        self.assertEqual(set(r), {"id", "text", "labels", "state", "created_by",
                                  "created_at", "closed_at", "note"})
        self.assertEqual(r["labels"], ["config"])
        self.assertEqual(r["state"], "open")

    def test_created_by_is_the_calling_agent(self):
        self.as_agent("w1")
        self.assertEqual(self.data("plugin", "todo", "add", "x")["created_by"], "w1")

    def test_created_by_is_provenance_and_not_assignment(self):
        """There is nowhere to say who should do it, and that is the feature. No `claim`,
        no `release`, no `owner` — a store that can assign work is a queue, and a queue is
        a scheduler."""
        p = plugins.load(self.repo, "todo")
        self.assertEqual(sorted(p.commands), ["add", "done", "drop", "list", "show"])
        for c in p.commands.values():
            self.assertNotIn("owner", [a.dest for a in c.args])

    # -- the open vocabulary (C12) --------------------------------------

    def test_state_declares_no_choices(self):
        """The named failure is a shipped system whose role vocabulary became an enum and
        whose every add-one request was closed unimplemented. Asserted on the declaration,
        not on behaviour, because this is the line somebody would 'tidy up'."""
        p = plugins.load(self.repo, "todo")
        for c in p.commands.values():
            for a in c.args:
                with self.subTest(command=c.name, arg=a.name):
                    self.assertIsNone(a.choices)

    def test_a_state_nobody_shipped_works_with_no_edit_to_sb(self):
        self.ok("plugin", "todo", "add", "waiting on review", "--state", "blocked")
        rows = self.data("plugin", "todo", "list", "--state", "blocked")
        self.assertEqual([r["text"] for r in rows], ["waiting on review"])

    def test_an_unshipped_state_still_lists_by_default(self):
        """The default filter is structural — closed or not — rather than a word, so a
        state sb has never heard of does not vanish from a bare `list`. A vocabulary that
        is open only to `--state` is not open."""
        self.ok("plugin", "todo", "add", "blocked thing", "--state", "blocked")
        self.assertEqual([r["text"] for r in self.data("plugin", "todo", "list")],
                         ["blocked thing"])

    # -- listing ---------------------------------------------------------

    # -- closing ---------------------------------------------------------

    def test_done_records_the_note_and_the_time(self):
        self.ok("plugin", "todo", "add", "a")
        r = self.data("plugin", "todo", "done", "t-1", "--note", "landed in phase 4")
        self.assertEqual(r["state"], "done")
        self.assertEqual(r["note"], "landed in phase 4")
        self.assertTrue(r["closed_at"])

    def test_closing_twice_does_not_restamp_the_time(self):
        self.ok("plugin", "todo", "add", "a")
        first = self.data("plugin", "todo", "done", "t-1")
        code, _, err = self.sb("plugin", "todo", "done", "t-1")
        self.assertEqual(code, 1)
        self.assertIn("already done", err)
        self.assertEqual(self.data("plugin", "todo", "show", "t-1")["closed_at"],
                         first["closed_at"])

    def test_drop_marks_dropped_rather_than_deleting_the_row(self):
        """Deleting would make an id cite nothing, which is the one property §9.2 spends
        its `next_id` counter to protect."""
        self.ok("plugin", "todo", "add", "not going to happen")
        r = self.data("plugin", "todo", "drop", "t-1", "--note", "out of scope")
        self.assertEqual(r["state"], "dropped")
        self.assertEqual(self.data("plugin", "todo", "show", "t-1")["id"], "t-1")

    def test_drop_is_for_the_human(self):
        self.as_agent("w1")
        self.ok("plugin", "todo", "add", "x")
        code, _, err = self.sb("plugin", "todo", "drop", "t-1")
        self.assertEqual(code, 1)
        self.assertIn("for the human", err)
        self.assertEqual(self.data("plugin", "todo", "show", "t-1")["state"], "open")

    # -- ids and refusals ------------------------------------------------

    def test_an_unknown_id_names_the_highest_one_there_is(self):
        self.ok("plugin", "todo", "add", "a")
        code, _, err = self.sb("plugin", "todo", "show", "t-9")
        self.assertEqual(code, 1)
        self.assertIn("the highest is t-1", err)

    # -- the file --------------------------------------------------------

    def _todos(self) -> Path:
        return store.store_dir(self.repo) / "plugins" / "todo" / "todos.json"


# -- report-bug (§10) ----------------------------------------------------------


class SessionTailTest(ShippedSandbox):
    """The `## session` block — a bounded tail of the filing agent's pane.

    Its whole risk profile is the failure path: the most likely reason anyone is filing a
    bug is that sb is misbehaving, so the tail is fetched by shelling out to the very tool
    being reported on. Every one of those failures has to end in a report that still exists.

    The tail logic is tested against `_session_tail` directly, with an agent name passed in.
    The sandbox has no calling agent, so an end-to-end file would short-circuit on the
    no-agent guard and assert nothing — which is exactly what the first version of these
    tests did.
    """

    def _dir(self) -> Path:
        return self.user_state / "plugins" / "report-bug"

    def _plugin_module(self):
        """The imported plugin module, reached the way sb reaches it.

        sb imports it under a mangled name (`sb_plugin_report-bug`) so nothing can reach a
        plugin by importing it normally. Loading it by path here would produce a DIFFERENT
        module object and patching that would patch nothing — so this loads it sb's way and
        then fetches the object sb put in `sys.modules`, which is the one the handler runs
        against.
        """
        plugins.load(self.repo, "report-bug")
        return sys.modules["sb_plugin_report-bug"]

    @contextlib.contextmanager
    def _inspect(self, mod, *, stdout=None, exc=None):
        """Intercept only the `sb inspect` subprocess, and let every other one through.

        `subprocess` is one shared module object, so patching `run` outright also patches
        the `git describe` and `herdr --version` probes. The first version of this did
        exactly that and failed for a reason that had nothing to do with the tail.
        """
        real = mod.subprocess.run

        def fake(cmd, *a, **kw):
            if list(cmd[:2]) != ["sb", "inspect"]:
                return real(cmd, *a, **kw)
            if exc is not None:
                raise exc
            return mock.Mock(returncode=0, stdout=stdout)

        with mock.patch.object(mod.subprocess, "run", side_effect=fake):
            yield

    def test_a_human_filing_gets_no_session_block(self):
        """No agent, no session — and no subprocess either. This is the end-to-end path
        for a person at a terminal, which is how most reports here get filed."""
        self.ok("plugin", "report-bug", "file", "sb delegate hangs")
        (f,) = self._dir().glob("*.md")
        self.assertNotIn("## session", f.read_text())

    def test_no_agent_means_no_lookup_at_all(self):
        mod = self._plugin_module()
        with mock.patch.object(mod.subprocess, "run",
                               side_effect=AssertionError("must not shell out")):
            self.assertEqual(mod._session_tail(None), "")

    def test_the_tail_is_clipped_to_the_cap_however_much_comes_back(self):
        """`-n` is a request to `sb inspect`; the cap here is the guarantee. A future
        inspect that over-delivers must not turn a bounded tail into a transcript."""
        mod = self._plugin_module()
        flood = "\n".join(f"line {i}" for i in range(500))
        with self._inspect(mod, stdout=json.dumps({"output": {"text": flood}})):
            tail = mod._session_tail("qa-3")
        lines = tail.splitlines()
        self.assertEqual(len(lines), mod.TAIL_LINES)
        self.assertEqual(lines[-1], "line 499")     # the END of the pane, not the start
        self.assertEqual(lines[0], f"line {500 - mod.TAIL_LINES}")

    def test_a_broken_inspect_costs_the_section_not_the_report(self):
        """The failure that matters: sb misbehaving is the expected condition here."""
        mod = self._plugin_module()
        for exc in (OSError("sb is not on PATH"),
                    mod.subprocess.TimeoutExpired(cmd="sb", timeout=5)):
            with self.subTest(exc=type(exc).__name__):
                with self._inspect(mod, exc=exc):
                    self.assertEqual(mod._session_tail("qa-3"), "")

    def test_a_non_zero_exit_or_malformed_json_is_not_a_crash(self):
        mod = self._plugin_module()
        with self._inspect(mod, stdout="not json at all"):
            self.assertEqual(mod._session_tail("qa-3"), "")
        with self._inspect(mod, stdout=json.dumps({"output": None})):
            self.assertEqual(mod._session_tail("qa-3"), "")
        with self._inspect(mod, stdout=json.dumps({})):
            self.assertEqual(mod._session_tail("qa-3"), "")

    def test_the_tail_is_fenced_and_comes_last(self):
        """Terminal output is full of characters markdown would eat, and it is the one
        open-ended part of the file — so it is fenced, and it sits after the facts."""
        import time as _time
        mod = self._plugin_module()
        pane = "$ sb cleanup\n0 agents cleaned up\n# not a heading"
        with self._inspect(mod, stdout=json.dumps({"output": {"text": pane}})):
            body = mod._render(
                mock.Mock(agent="qa-3", repo="/r", worktree="/w"),
                mock.Mock(command="sb cleanup", expected="closed", actual="nothing"),
                "cleanup does nothing", _time.localtime())
        self.assertIn(f"## session (last {mod.TAIL_LINES} lines)", body)
        self.assertIn("```\n$ sb cleanup", body)
        self.assertIn("# not a heading", body)      # survives, because it is fenced
        self.assertGreater(body.index("## session"), body.index("## context"))


class ReportBugTest(ShippedSandbox):

    def test_the_filename_is_a_timestamp_and_a_slug(self):
        r = self.data("plugin", "report-bug", "file", "sb delegate hangs forever")
        self.assertRegex(r["id"], r"^\d{4}-\d\d-\d\d-\d{6}-sb-delegate-hangs-forever$")

    def test_state_is_per_machine_not_per_repo(self):
        self.ok("plugin", "report-bug", "file", "x")
        self.assertEqual(self._dir(), self.user_state / "plugins" / "report-bug")
        self.assertFalse((store.store_dir(self.repo) / "plugins" / "report-bug").exists())

    def test_the_narrative_sections_are_the_callers(self):
        self.ok("plugin", "report-bug", "file", "it broke",
                "--command", "sb delegate x", "--expected", "a spawn",
                "--actual", "KeyError: role")
        text = self._only().read_text()
        self.assertIn("# it broke", text)
        self.assertIn("sb delegate x", text)
        self.assertIn("KeyError: role", text)

    def test_the_context_is_captured_without_being_asked_for(self):
        self.ok("plugin", "report-bug", "file", "it broke")
        text = self._only().read_text()
        for field in ("- sb:", "- herdr:", "- python:", "- platform:",
                      "- repo:", "- worktree:", "- by:"):
            self.assertIn(field, text)

    def test_the_repo_and_worktree_are_recorded_in_the_file(self):
        """Recorded, not partitioned on. Both, because they are different facts: `repo` is
        the shared `.git` identity and `worktree` is the checkout you were standing in."""
        self.ok("plugin", "report-bug", "file", "it broke")
        text = self._only().read_text()
        self.assertIn(f"- repo: {store.repo_root(self.repo)}", text)
        self.assertIn(f"- worktree: {self.repo.resolve()}", text)

    def test_no_transcript_is_captured(self):
        """A transcript contains everything the agent read. Hoovering it into a bug report
        by default is a data-exfiltration shape even with no publishing step."""
        self.ok("plugin", "report-bug", "file", "it broke")
        text = self._only().read_text().lower()
        self.assertNotIn("transcript", text)
        self.assertNotIn(".jsonl", text)

    def test_list_is_newest_first(self):
        for what in ("first bug", "second bug"):
            self.ok("plugin", "report-bug", "file", what)
        got = [r["what"] for r in self.data("plugin", "report-bug", "list")]
        self.assertEqual(got[0], "second bug")

    def test_list_is_not_filtered_by_repo(self):
        """Filing three bugs in three repos and finding none of them again is the exact
        failure user scope exists to prevent, and a repo-shaped default view would put it
        straight back."""
        self.ok("plugin", "report-bug", "file", "from here")
        (self._dir() / "2020-01-01-000000-elsewhere.md").write_text(
            "# from another repo\n\n## context\n\n- worktree: /somewhere/else\n")
        got = [r["what"] for r in self.data("plugin", "report-bug", "list")]
        self.assertIn("from another repo", got)

    def test_an_ambiguous_prefix_names_the_candidates(self):
        for what in ("bug one", "bug two"):
            self.ok("plugin", "report-bug", "file", what)
        code, _, err = self.sb("plugin", "report-bug", "show", "20")
        self.assertEqual(code, 1)
        self.assertIn("matches 2 reports", err)

    def test_drop_deletes_the_file(self):
        """A report is a file, so `drop` unlinks it. `todo drop` marks instead, because a
        todo is a ledger row that something may cite by id — different things, on purpose."""
        r = self.data("plugin", "report-bug", "file", "x")
        self.ok("plugin", "report-bug", "drop", r["id"])
        self.assertEqual(list(self._dir().glob("*.md")), [])

    def test_drop_is_for_the_human(self):
        self.as_agent("w1")
        r = self.data("plugin", "report-bug", "file", "x")
        code, _, err = self.sb("plugin", "report-bug", "drop", r["id"])
        self.assertEqual(code, 1)
        self.assertIn("for the human", err)
        self.assertEqual(len(list(self._dir().glob("*.md"))), 1)

    def test_no_github_is_involved(self):
        source = (config.defaults_dir() / "plugins" / "report-bug"
                  / "__init__.py").read_text().lower()
        for word in ("github", "http://", "https://", "urllib", "requests"):
            self.assertNotIn(word, source)

    def _dir(self) -> Path:
        return self.user_state / "plugins" / "report-bug"

    def _only(self) -> Path:
        (p,) = list(self._dir().glob("*.md"))
        return p


# -- doctor --------------------------------------------------------------------


class DoctorTest(ShippedSandbox):
    """What `sb doctor` says about plugins, and what it does NOT do about it."""

    def test_a_healthy_repo_is_clean_and_exits_zero(self):
        code, out, _ = self.sb("doctor")
        self.assertEqual(code, 0, out)
        self.assertNotIn("PROBLEM", out)
        self.assertNotIn("note", out)

    def test_a_broken_plugin_is_a_problem_and_a_non_zero_exit(self):
        self.ship("halfthing", "raise SystemExit(3)\n")
        self.enable("halfthing")
        code, out, _ = self.sb("doctor")
        self.assertEqual(code, 1)
        self.assertIn("plugin 'halfthing' broken", out)
        self.assertNotIn("Traceback", out)

    def test_an_incompatible_plugin_is_a_problem(self):
        """§11 item 4: incompatibility is deliberately NOT enforced at spawn, because
        `delegate` never imports. `doctor` is the only place it is visible before an agent
        runs a command that refuses."""
        self.ship("shiny", "API = 2\nVERSION = '2.0.0'\ndef register(reg): pass\n")
        self.enable("shiny")
        code, out, _ = self.sb("doctor")
        self.assertEqual(code, 1)
        self.assertIn("plugin 'shiny' incompatible", out)
        self.assertIn("API 2", out)

    def test_a_plugin_loaded_from_the_repo_is_named(self):
        self.local("mine", "API = 1\nVERSION = '0.1'\n"
                           "def register(reg): reg.command('go', lambda c, a: None)\n")
        self.enable("mine")
        code, out, _ = self.sb("doctor")
        self.assertIn("plugin 'mine' is loaded from", out)
        self.assertIn(".switchboard/plugins/", out)
        # Visibility, not a gate. There is no trust prompt, and the exit code does not move:
        # whoever can write `.switchboard/plugins/` can already run code here via
        # conftest.py or a git hook. What doctor adds is that you find out.
        self.assertEqual(code, 0)

    def test_an_orphaned_state_directory_is_reported_with_the_rm(self):
        d = store.store_dir(self.repo) / "plugins" / "ci-check"
        d.mkdir(parents=True)
        (d / "data.json").write_text("{}")
        code, out, _ = self.sb("doctor")
        self.assertIn("orphaned plugin state:", out)
        self.assertIn(str(d), out)
        self.assertIn("rm -rf to discard", out)
        self.assertEqual(code, 0)

    def test_a_disabled_plugins_state_is_not_an_orphan(self):
        """Disabling does not touch state and re-enabling finds it intact, so a disabled
        plugin's directory is not orphaned and reporting it would teach the wrong `rm`."""
        (self.sw / "plugins.toml").write_text('enabled = ["todo"]\n')
        self.ok("plugin", "todo", "add", "a")
        (self.sw / "plugins.toml").write_text('enabled = ["!reset"]\n')
        _, out, _ = self.sb("doctor")
        self.assertNotIn("orphaned", out)

    # -- §8.2, the transition -------------------------------------------

    def test_a_preset_in_the_pre_rename_directory_gets_its_git_mv(self):
        old = self.sw / "plugins"
        old.mkdir(parents=True, exist_ok=True)
        (old / "legacy.md").write_text("# legacy\ntext")
        _, out, _ = self.sb("doctor")
        self.assertIn("git mv .switchboard/plugins/legacy.md "
                      ".switchboard/presets/legacy.md", out)

    def test_a_pre_rename_preset_that_is_no_longer_read_says_so(self):
        old = self.sw / "plugins"
        old.mkdir(parents=True, exist_ok=True)
        (old / "legacy.md").write_text("# legacy\ntext")
        (self.sw / "presets").mkdir(parents=True, exist_ok=True)
        _, out, _ = self.sb("doctor")
        self.assertIn("ignored", out)

    def test_a_pre_rename_bindings_file_gets_its_git_mv(self):
        (self.sw / "plugins.toml").write_text('all = ["own-files"]\n')
        _, out, _ = self.sb("doctor")
        self.assertIn("git mv .switchboard/plugins.toml .switchboard/presets.toml", out)

    def test_a_file_holding_both_meanings_is_told_to_split_rather_than_move(self):
        """`git mv` would carry the enablement away with the bindings. The keys are
        disjoint and the file parses correctly as both — the fix is a split."""
        (self.sw / "plugins.toml").write_text('enabled = ["todo"]\nall = ["own-files"]\n')
        _, out, _ = self.sb("doctor")
        self.assertIn("holds both meanings", out)
        self.assertNotIn("git mv .switchboard/plugins.toml", out)

    def test_bindings_left_behind_in_a_dead_file_are_named(self):
        (self.sw / "plugins.toml").write_text('all = ["own-files"]\n')
        (self.sw / "presets.toml").write_text('all = ["verify"]\n')
        _, out, _ = self.sb("doctor")
        self.assertIn("are ignored", out)

    # -- the json surface -----------------------------------------------

    def test_json_carries_every_finding(self):
        self.ship("halfthing", "raise SystemExit(3)\n")
        self.enable("halfthing")
        (store.store_dir(self.repo) / "plugins" / "ci-check").mkdir(parents=True)
        code, out, _ = self.sb("doctor", "--json")
        d = json.loads(out)
        self.assertEqual(code, 1)
        self.assertFalse(d["ok"])
        self.assertTrue(d["plugin_problems"])
        self.assertEqual([o["name"] for o in d["orphaned_state"]], ["ci-check"])
        self.assertIn("halfthing", [p["name"] for p in d["plugins"]])

if __name__ == "__main__":
    unittest.main()
