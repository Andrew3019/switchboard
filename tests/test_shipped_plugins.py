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

    def test_both_plugins_ship_enabled(self):
        self.assertEqual(sorted(plugins.enabled(self.repo)), ["report-bug", "todo"])

    def test_both_plugins_ship_bound_to_every_agent(self):
        self.assertEqual(plugins.bound(self.repo),
                         {"todo": ["every agent"], "report-bug": ["every agent"]})

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

    def test_unbinding_keeps_the_commands(self):
        """`all = ["!reset"]` — stop taxing every spawn, keep `sb plugin todo`. This is the
        option that collapsing the three states into two would have made unsayable."""
        (self.sw / "presets.toml").write_text('all = ["!reset"]\n')
        self.assertEqual(presets.for_role(self.repo, "builder"), [])
        self.assertEqual(sorted(plugins.enabled(self.repo)), ["report-bug", "todo"])
        self.assertIn("t-1", self.ok("plugin", "todo", "add", "still works"))

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

    def test_the_two_levers_are_independent(self):
        """Unbinding does not disable and disabling does not unbind — the whole reason
        §7.2 keeps three states rather than two."""
        (self.sw / "plugins.toml").write_text('enabled = ["!reset"]\n')
        self.assertEqual(plugins.bound(self.repo),
                         {"todo": ["every agent"], "report-bug": ["every agent"]})


# -- todo (§9) -----------------------------------------------------------------


class TodoTest(ShippedSandbox):
    def test_add_files_a_todo_and_names_its_id(self):
        out = self.ok("plugin", "todo", "add", "write the brief")
        self.assertIn("t-1", out)
        self.assertIn("write the brief", out)

    def test_ids_are_monotonic(self):
        for _ in range(3):
            self.ok("plugin", "todo", "add", "x")
        self.assertEqual([r["id"] for r in self.data("plugin", "todo", "list")],
                         ["t-1", "t-2", "t-3"])

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

    def test_created_by_is_the_human_when_a_human_types(self):
        self.assertEqual(self.data("plugin", "todo", "add", "x")["created_by"], "human")

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

    def test_the_default_list_hides_closed_todos(self):
        self.ok("plugin", "todo", "add", "a")
        self.ok("plugin", "todo", "add", "b")
        self.ok("plugin", "todo", "done", "t-1")
        self.assertEqual([r["id"] for r in self.data("plugin", "todo", "list")], ["t-2"])

    def test_all_includes_them(self):
        self.ok("plugin", "todo", "add", "a")
        self.ok("plugin", "todo", "done", "t-1")
        self.assertEqual([r["id"] for r in self.data("plugin", "todo", "list", "--all")],
                         ["t-1"])

    def test_labels_filter_conjunctively(self):
        self.ok("plugin", "todo", "add", "a", "--label", "x", "--label", "y")
        self.ok("plugin", "todo", "add", "b", "--label", "x")
        got = self.data("plugin", "todo", "list", "--label", "x", "--label", "y")
        self.assertEqual([r["text"] for r in got], ["a"])

    def test_an_empty_list_says_so_rather_than_printing_nothing(self):
        self.assertIn("no open todos", self.ok("plugin", "todo", "list"))

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

    def test_done_is_not(self):
        self.as_agent("w1")
        self.ok("plugin", "todo", "add", "x")
        self.assertEqual(self.data("plugin", "todo", "done", "t-1")["state"], "done")

    # -- ids and refusals ------------------------------------------------

    def test_a_bare_number_names_the_same_todo(self):
        self.ok("plugin", "todo", "add", "a")
        self.assertEqual(self.data("plugin", "todo", "show", "1")["id"], "t-1")

    def test_an_unknown_id_names_the_highest_one_there_is(self):
        self.ok("plugin", "todo", "add", "a")
        code, _, err = self.sb("plugin", "todo", "show", "t-9")
        self.assertEqual(code, 1)
        self.assertIn("the highest is t-1", err)

    def test_an_id_that_is_not_an_id_says_what_one_looks_like(self):
        code, _, err = self.sb("plugin", "todo", "show", "banana")
        self.assertEqual(code, 1)
        self.assertIn("t-7", err)

    def test_an_empty_todo_is_refused(self):
        code, _, err = self.sb("plugin", "todo", "add", "   ")
        self.assertEqual(code, 1)
        self.assertIn("needs some text", err)

    def test_a_failure_is_ok_false_under_json(self):
        code, out, _ = self.sb("plugin", "todo", "show", "t-9", "--json")
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out)["ok"])

    # -- the file --------------------------------------------------------

    def test_state_lives_under_the_shared_git_and_not_in_the_store(self):
        self.ok("plugin", "todo", "add", "a")
        self.assertEqual(self._todos().parent,
                         store.store_dir(self.repo) / "plugins" / "todo")
        self.assertTrue(self._todos().is_file())

    def test_the_file_is_json_a_person_can_read(self):
        self.ok("plugin", "todo", "add", "a")
        text = self._todos().read_text()
        self.assertIn("\n", text)                       # indented, not one line
        self.assertEqual(json.loads(text)["todos"][0]["text"], "a")

    def test_no_temporary_file_survives_a_write(self):
        self.ok("plugin", "todo", "add", "a")
        self.assertEqual([p.name for p in self._todos().parent.iterdir()
                          if p.name.endswith(".tmp")], [])

    def test_the_lock_is_declared(self):
        self.assertTrue(plugins.load(self.repo, "todo").lock)

    def _todos(self) -> Path:
        return store.store_dir(self.repo) / "plugins" / "todo" / "todos.json"


# -- report-bug (§10) ----------------------------------------------------------


class ReportBugTest(ShippedSandbox):
    def test_filing_writes_one_markdown_file(self):
        self.ok("plugin", "report-bug", "file", "sb delegate hangs")
        self.assertEqual(len(list(self._dir().glob("*.md"))), 1)

    def test_the_filename_is_a_timestamp_and_a_slug(self):
        r = self.data("plugin", "report-bug", "file", "sb delegate hangs forever")
        self.assertRegex(r["id"], r"^\d{4}-\d\d-\d\d-\d{6}-sb-delegate-hangs-forever$")

    def test_the_same_bug_filed_twice_is_two_files(self):
        """No dedup, on purpose: the same bug filed three times is three files, and three
        files is itself the reproduction signal."""
        a = self.data("plugin", "report-bug", "file", "same words")
        b = self.data("plugin", "report-bug", "file", "same words")
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(len(list(self._dir().glob("*.md"))), 2)

    def test_state_is_per_machine_not_per_repo(self):
        self.ok("plugin", "report-bug", "file", "x")
        self.assertEqual(self._dir(), self.user_state / "plugins" / "report-bug")
        self.assertFalse((store.store_dir(self.repo) / "plugins" / "report-bug").exists())

    def test_no_lock_is_taken(self):
        p = plugins.load(self.repo, "report-bug")
        self.assertFalse(p.lock)
        self.ok("plugin", "report-bug", "file", "x")
        self.assertFalse((self._dir() / ".lock").exists())

    def test_the_narrative_sections_are_the_callers(self):
        self.ok("plugin", "report-bug", "file", "it broke",
                "--command", "sb delegate x", "--expected", "a spawn",
                "--actual", "KeyError: role")
        text = self._only().read_text()
        self.assertIn("# it broke", text)
        self.assertIn("sb delegate x", text)
        self.assertIn("KeyError: role", text)

    def test_an_omitted_section_is_absent_rather_than_empty(self):
        self.ok("plugin", "report-bug", "file", "it broke")
        self.assertNotIn("## expected", self._only().read_text())

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

    def test_the_calling_agent_is_recorded(self):
        self.as_agent("w1")
        self.ok("plugin", "report-bug", "file", "it broke")
        self.assertIn("- by: w1", self._only().read_text())

    def test_no_transcript_is_captured(self):
        """A transcript contains everything the agent read. Hoovering it into a bug report
        by default is a data-exfiltration shape even with no publishing step."""
        self.ok("plugin", "report-bug", "file", "it broke")
        text = self._only().read_text().lower()
        self.assertNotIn("transcript", text)
        self.assertNotIn(".jsonl", text)

    def test_the_sb_version_is_marked_dirty_when_the_checkout_is(self):
        """`--dirty` is the point: most reports will be filed against uncommitted work, and
        a report claiming the commit it was almost built from is worse than one that says
        it does not know."""
        self.ok("plugin", "report-bug", "file", "it broke")
        line = next(x for x in self._only().read_text().splitlines()
                    if x.startswith("- sb:"))
        self.assertTrue(line.split(":", 1)[1].strip())

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

    def test_an_empty_store_says_so(self):
        self.assertIn("no bug reports", self.ok("plugin", "report-bug", "list"))

    def test_show_takes_an_unambiguous_prefix(self):
        r = self.data("plugin", "report-bug", "file", "a very specific bug")
        out = self.ok("plugin", "report-bug", "show", r["id"][:13])
        self.assertIn("a very specific bug", out)

    def test_an_ambiguous_prefix_names_the_candidates(self):
        for what in ("bug one", "bug two"):
            self.ok("plugin", "report-bug", "file", what)
        code, _, err = self.sb("plugin", "report-bug", "show", "20")
        self.assertEqual(code, 1)
        self.assertIn("matches 2 reports", err)

    def test_an_unknown_id_is_refused(self):
        code, _, err = self.sb("plugin", "report-bug", "show", "nope")
        self.assertEqual(code, 1)
        self.assertIn("no such report", err)

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

    def test_an_empty_summary_is_refused(self):
        code, _, err = self.sb("plugin", "report-bug", "file", "  ")
        self.assertEqual(code, 1)
        self.assertIn("what broke", err)

    def test_a_summary_of_only_punctuation_still_gets_a_filename(self):
        r = self.data("plugin", "report-bug", "file", "!!! ???")
        self.assertTrue(r["id"].endswith("-bug"))

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

    def test_one_broken_plugin_does_not_hide_the_rest_of_the_report(self):
        self.ship("halfthing", "raise SystemExit(3)\n")
        self.enable("halfthing")
        _, out, _ = self.sb("doctor")
        self.assertIn("herdr", out)
        self.assertIn("store", out)

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

    def test_an_orphan_is_never_deleted(self):
        d = store.store_dir(self.repo) / "plugins" / "ci-check"
        d.mkdir(parents=True)
        (d / "data.json").write_text('{"mine": true}')
        self.sb("doctor")
        self.assertEqual((d / "data.json").read_text(), '{"mine": true}')

    def test_a_user_scoped_orphan_is_found_too(self):
        d = self.user_state / "plugins" / "gone"
        d.mkdir(parents=True)
        _, out, _ = self.sb("doctor")
        self.assertIn(str(d), out)

    def test_a_disabled_plugins_state_is_not_an_orphan(self):
        """Disabling does not touch state and re-enabling finds it intact, so a disabled
        plugin's directory is not orphaned and reporting it would teach the wrong `rm`."""
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

    def test_none_of_the_transition_notices_move_the_exit_code(self):
        (self.sw / "plugins.toml").write_text('all = ["own-files"]\n')
        code, _, _ = self.sb("doctor")
        self.assertEqual(code, 0)

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

    def test_ok_is_true_when_only_notices_are_present(self):
        (store.store_dir(self.repo) / "plugins" / "ci-check").mkdir(parents=True)
        _, out, _ = self.sb("doctor", "--json")
        self.assertTrue(json.loads(out)["ok"])


if __name__ == "__main__":
    unittest.main()
