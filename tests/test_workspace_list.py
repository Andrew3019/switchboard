"""`sb workspace list`, the already-gone close, and the rule that keeps a name single.

The listing exists because finding out what has accumulated currently means
cross-referencing `git worktree list` against the store by hand, so it has to hold every
side of that cross-reference. Its load-bearing property is the union: three sources, each
knowing something the other two cannot, and a listing built on any one of them is a
listing that lies. One test per source.

The close here is the already-gone path — a checkout that is no longer there, which is the
cheapest safe win and needs none of a destructive command's machinery. What it does need is
that it names the one path (a bare `git worktree prune` is repo-global and takes every
prunable checkout in the repository with it) and that `git branch -d` is left to refuse an
unmerged branch on its own. The other two routes a close can take — a checkout that still
exists, and a bare workspace — are tested in tests/test_workspace_close.py.

Real git here, not a fake: what git actually reports about worktrees and merged branches
is most of what is being tested.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import live, store  # noqa: E402
from switchboard.broker import HUMAN, Broker  # noqa: E402
from test_workspace import FakeHerdr  # noqa: E402


class Harness:
    """A real repo, a fake herdr, and a store on the side."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()   # git answers with the real path
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-q", "--allow-empty", "-m", "x")
        self.db = store.connect(path=self.root / "state.db")
        self.h = FakeHerdr(self.root / "worktrees")
        self.b = Broker(self.db, self.h, repo=self.repo)
        self.scan = live.scan
        live.scan = lambda *a, **kw: []          # nothing live, unless a test says so

    def tearDown(self):
        live.scan = self.scan
        self.db.close()
        self.tmp.cleanup()

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=str(cwd or self.repo),
                              capture_output=True, text=True)

    def worktree(self, name: str, *, commit: bool = False) -> str:
        """A real linked checkout of `name`, as `_attach_workspace` would end up with."""
        path = self.root / "wt" / name
        self.git("worktree", "add", "-q", str(path), "-b", name)
        if commit:
            self.git("-c", "user.email=t@t", "-c", "user.name=t",
                     "commit", "-q", "--allow-empty", "-m", "work", cwd=path)
        return str(path)

    def row(self, name: str, **kw):
        store.create_agent(self.db, name=name, role="worker", parent=None, task="t",
                           session_id=None, cwd=kw.get("cwd"),
                           workspace=kw.get("workspace"), branch=kw.get("branch"),
                           workspace_id="", terminal_id=None, pane_id=None,
                           cleanup="close", awaiting_task=False)
        if kw.get("state"):
            store.set_state(self.db, name, kw["state"])

    def listed(self) -> dict:
        return {w["name"]: w for w in self.b.workspace_list()["workspaces"]}


class ListingTest(Harness, unittest.TestCase):
    """The union of three sources: one test per source, each naming something the other
    two cannot see."""

    def test_only_git_knows_a_checkout_nobody_was_ever_recorded_in(self):
        path = self.worktree("orphan")
        w = self.listed()["orphan"]
        self.assertEqual(w["sources"], ["git"])
        self.assertEqual(w["checkout"], path)
        self.assertEqual(w["verdict"], store.CHECKOUT_OK)
        self.assertEqual(w["rows"], {"total": 0, "unfinished": 0})

    def test_only_the_table_knows_a_retired_workspace_with_no_rows(self):
        store.record_workspace(self.db, "gone-for-good", "/wt/gone-for-good")
        store.retire_workspace(self.db, "gone-for-good")
        w = self.listed()["gone-for-good"]
        self.assertEqual(w["sources"], ["table"])
        self.assertEqual(w["verdict"], "retired")
        self.assertIsNone(w["checkout"])

    def test_only_the_agent_rows_know_a_workspace_that_escaped_the_table(self):
        path = str(self.root / "elsewhere")     # not in git's registry either
        self.row("escaped-lead", workspace="escaped", branch="escaped", cwd=path)
        w = self.listed()["escaped"]
        self.assertEqual(w["sources"], ["agents"])
        self.assertEqual(w["checkout"], path)               # read off its own rows
        self.assertEqual(w["rows"]["total"], 1)

    def test_bare_workspaces_are_four_names_and_not_one_checkout(self):
        """The reason the union cannot start from git: `git worktree list` shows the
        primary checkout once, so four orchestrators over it are invisible from that side.
        A NULL checkout is the fact that they are bare, not a gap in the record."""
        for n in ("main", "main-2", "main-3", "main-4"):
            store.record_workspace(self.db, n, None)
        listed = self.listed()
        for n in ("main", "main-2", "main-3", "main-4"):
            self.assertEqual(listed[n]["verdict"], "bare")
            self.assertIsNone(listed[n]["checkout"])

    def test_a_workspace_all_three_sources_know_is_listed_once(self):
        path = self.worktree("api")
        store.record_workspace(self.db, "api", path)
        self.row("api-lead", workspace="api", branch="api", cwd=path)
        self.assertEqual(self.listed()["api"]["sources"], ["agents", "git", "table"])

    # -- the state of each one --------------------------------------------

    def test_a_recorded_path_whose_directory_is_gone_reads_absent_not_unusable(self):
        """`absent` is a resolved answer — nothing is there, so nothing can be lost — and
        it is what routes a workspace to the already-gone close."""
        path = self.worktree("stale")
        store.record_workspace(self.db, "stale", path)
        shutil.rmtree(path)
        self.assertEqual(self.listed()["stale"]["verdict"], store.CHECKOUT_ABSENT)

    def test_an_unmerged_branch_is_flagged_because_a_safe_delete_will_refuse_it(self):
        self.worktree("merged-work")
        self.worktree("own-work", commit=True)
        listed = self.listed()
        self.assertTrue(listed["own-work"]["unmerged"])
        self.assertFalse(listed["merged-work"]["unmerged"])

    def test_ignored_content_is_weighed_and_switchboards_own_furniture_is_not(self):
        (self.repo / ".gitignore").write_text(".env\nCLAUDE.md\n")
        self.git("add", ".gitignore")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "ig")
        path = Path(self.worktree("api"))
        (path / ".env").write_text("SECRET=1")
        (self.repo / "CLAUDE.md").write_text("hello")
        (path / "CLAUDE.md").symlink_to(self.repo / "CLAUDE.md")
        w = self.listed()["api"]
        self.assertEqual(w["ignored"]["unknown"], 1)        # the .env, which is theirs
        self.assertEqual(w["ignored"]["sample"], [".env"])
        self.assertEqual(w["ignored"]["mine"], 1)           # the symlink, which is ours

    # -- the live observation, exercised read-only ------------------------

    def test_a_process_in_the_checkout_is_reported(self):
        path = self.worktree("api")
        live.scan = lambda *a, **kw: [live.Proc(11, "vim", f"{path}/switchboard")]
        w = self.listed()["api"]
        self.assertEqual(w["live_verdict"], "live")
        self.assertEqual(w["live"][0]["command"], "vim")

    def test_a_scan_that_could_not_be_made_reads_unknown_and_never_empty(self):
        self.worktree("api")
        live.scan = lambda *a, **kw: None
        self.assertEqual(self.listed()["api"]["live_verdict"], "unknown")

    def test_a_sibling_whose_name_is_a_string_prefix_is_not_in_this_checkout(self):
        api = self.worktree("api")
        self.worktree("api-2")
        live.scan = lambda *a, **kw: [live.Proc(11, "vim", f"{api}-2/switchboard")]
        listed = self.listed()
        self.assertEqual(listed["api"]["live_verdict"], "clear")
        self.assertEqual(listed["api-2"]["live_verdict"], "live")

    # -- the never-filled store -------------------------------------------

    def test_an_unfilled_store_says_so_rather_than_reading_as_having_no_workspaces(self):
        self.db.execute("DELETE FROM meta WHERE key='backfill:workspaces'")
        self.db.commit()
        self.assertIn("never been filled in", self.b.workspace_list()["gap"])

    def test_close_refuses_while_the_store_cannot_be_asked_about_workspaces(self):
        store.record_workspace(self.db, "stale", str(self.root / "wt" / "stale"))
        self.db.execute("DELETE FROM meta WHERE key='backfill:workspaces'")
        self.db.commit()
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("stale", me=HUMAN)
        self.assertIn("never been filled in", str(e.exception))


class AlreadyGoneTest(Harness, unittest.TestCase):
    """The cheapest real win: a checkout that is no longer there."""

    def gone(self, name: str, *, commit: bool = False) -> str:
        path = self.worktree(name, commit=commit)
        store.record_workspace(self.db, name, path)
        shutil.rmtree(path)
        return path

    def registered(self) -> list[str]:
        return [wt["path"] for wt in self.b._worktrees()]

    def branches(self) -> set:
        return {ln.strip("* ").strip()
                for ln in (self.git("branch").stdout or "").splitlines() if ln.strip()}

    def test_it_deregisters_exactly_the_one_named_checkout(self):
        """Never a bare `git worktree prune`: one prune deregisters every prunable
        checkout in the repository, including one another agent has gated."""
        gone, also_gone = self.gone("stale"), self.gone("also-stale")
        keep = self.worktree("busy")
        r = self.b.workspace_close("stale", me=HUMAN)
        self.assertEqual(r["worktree"], "removed")
        self.assertNotIn(gone, self.registered())
        self.assertIn(also_gone, self.registered())         # prunable, and left alone
        self.assertIn(keep, self.registered())

    def test_it_deletes_a_merged_branch_and_retires_the_workspace(self):
        self.gone("stale")
        r = self.b.workspace_close("stale", me=HUMAN)
        self.assertTrue(r["branch_deleted"])
        self.assertNotIn("stale", self.branches())
        row = store.get_workspace(self.db, "stale")
        self.assertTrue(row["retired_at"])
        self.assertIsNone(row["checkout"])                  # retiring clears the path
        self.assertIsNone(row["retiring"])

    def test_an_unmerged_branch_simply_stays(self):
        """`-d`, never `-D`. An unmerged branch left standing is a far cheaper failure
        than losing commits, and the worktree is deregistered either way."""
        gone = self.gone("own-work", commit=True)
        r = self.b.workspace_close("own-work", me=HUMAN)
        self.assertFalse(r["branch_deleted"])
        self.assertIn("own-work", self.branches())
        self.assertNotIn(gone, self.registered())
        self.assertTrue(store.get_workspace(self.db, "own-work")["retired_at"])

    def test_a_checkout_that_is_still_there_takes_the_destructive_route_instead(self):
        """Which is a route and not this one: everything that guards a directory with
        something in it lives there. See tests/test_workspace_close.py."""
        path = self.worktree("api")
        store.record_workspace(self.db, "api", path)
        self.assertEqual(self.b.workspace_close("api", me=HUMAN)["kind"], "worktree")
        self.assertNotIn(path, self.registered())

    def test_an_unintelligible_path_is_refused_because_unknown_is_not_empty(self):
        store.record_workspace(self.db, "odd", str(self.root / "not-a-worktree"))
        (self.root / "not-a-worktree").mkdir()
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("odd", me=HUMAN)
        self.assertIn("cannot tell", str(e.exception))

    def test_a_bare_workspace_takes_its_own_route_and_loses_nothing(self):
        """No checkout of its own, so nothing to deregister and nothing to delete —
        retiring is the whole operation. See tests/test_workspace_close.py."""
        store.record_workspace(self.db, "main", None)
        r = self.b.workspace_close("main", me=HUMAN)
        self.assertEqual(r["kind"], "bare")
        self.assertTrue(store.get_workspace(self.db, "main")["retired_at"])

    def test_an_unfinished_row_under_the_path_refuses(self):
        gone = self.gone("stale")
        self.row("worker", workspace="stale", branch="stale", cwd=f"{gone}/sub")
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("stale", me=HUMAN)
        self.assertIn("worker", str(e.exception))
        self.assertIn(gone, self.registered())

    def test_a_row_in_a_sibling_whose_name_is_a_string_prefix_does_not_refuse(self):
        gone = self.gone("stale")
        self.worktree("stale-2")
        self.row("worker", workspace="stale-2", branch="stale-2", cwd=f"{gone}-2/sub")
        self.b.workspace_close("stale", me=HUMAN)
        self.assertNotIn(gone, self.registered())

    def test_a_finished_row_under_the_path_does_not_refuse(self):
        gone = self.gone("stale")
        self.row("worker", workspace="stale", branch="stale", cwd=gone, state="done")
        self.b.workspace_close("stale", me=HUMAN)
        self.assertNotIn(gone, self.registered())

    def test_a_mark_somebody_else_holds_refuses_and_names_them(self):
        self.gone("stale")
        store.claim_retiring(self.db, "stale", "other-agent")
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("stale", me=HUMAN)
        self.assertIn("other-agent", str(e.exception))

    def test_a_refusal_leaves_no_mark_behind(self):
        gone = self.gone("stale")
        self.row("worker", workspace="stale", branch="stale", cwd=gone)
        with self.assertRaises(ValueError):
            self.b.workspace_close("stale", me=HUMAN)
        self.assertIsNone(store.get_workspace(self.db, "stale")["retiring"])

    def test_closing_it_twice_is_not_an_error(self):
        """A directory that is already gone is a resumable state, not a failure."""
        self.gone("stale")
        self.b.workspace_close("stale", me=HUMAN)
        self.assertTrue(self.b.workspace_close("stale", me=HUMAN)["already"])

    def test_a_name_nothing_recorded_says_so(self):
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("never-heard-of-it", me=HUMAN)
        self.assertIn("nothing here to close", str(e.exception))


class OneNamespaceTest(Harness, unittest.TestCase):
    """A name is one kind of workspace or the other, never both.

    Two places mint names into one namespace and never used to consult each other: the
    auto-minter behind a bare `sb start`, whose freeness test asked the AGENTS table (and
    a worktree workspace's lead is called `<name>-lead`, so it never matched), and a human
    typing `sb workspace new <name>`. Under a name-keyed record those are one row
    describing two workspaces in two different directories — the same failure that
    disqualified keying on the path, arriving from the other side.
    """

    def test_a_bare_start_refuses_a_name_a_worktree_workspace_holds(self):
        self.b.workspace_new("api", me=HUMAN)
        with self.assertRaises(ValueError) as e:
            self.b.start(name="api")
        self.assertIn("checkout of its own", str(e.exception))   # which kind holds it
        self.assertIn("sb workspace new api", str(e.exception))  # and the way to it

    def test_a_new_workspace_refuses_a_name_a_bare_one_holds(self):
        self.b.start(name="main", board=False)
        with self.assertRaises(ValueError) as e:
            self.b.workspace_new("main", me=HUMAN)
        self.assertIn("no checkout of its own", str(e.exception))
        self.assertIn("sb start --name main", str(e.exception))

    def test_the_auto_minted_name_skips_one_a_worktree_workspace_holds(self):
        """`_next_top_name`'s freeness test asks about workspaces now, not only about an
        agent row that happens to share the string — a worktree workspace's lead is called
        `main-lead`, which is not the name being tested."""
        self.b.workspace_new("main", me=HUMAN)
        self.assertEqual(self.b.start(board=False), "main-2")

    def test_a_retired_name_is_free_again(self):
        """Retirement is a record of end-of-life, not a tombstone on the name."""
        self.b.workspace_new("api", me=HUMAN)
        store.retire_workspace(self.db, "api")
        self.b.start(name="api", board=False)               # no longer held
        self.assertIsNone(store.get_workspace(self.db, "api")["retired_at"])


class RecordedPathTest(Harness, unittest.TestCase):
    """The path is a record of where the checkout IS, not of where it once was."""

    def test_attaching_writes_the_path_down(self):
        r = self.b.workspace_new("api", me=HUMAN)
        self.assertEqual(store.get_workspace(self.db, "api")["checkout"], r["path"])

    def test_attaching_again_re_writes_it_from_the_workspace_actually_attached(self):
        self.b.workspace_new("api", me=HUMAN)
        store.record_workspace(self.db, "api", "/somewhere/else")
        r = self.b.workspace_new("api", me=HUMAN)
        self.assertEqual(store.get_workspace(self.db, "api")["checkout"], r["path"])

    def test_reopening_a_retired_workspace_clears_the_retirement_and_records_the_path(self):
        r = self.b.workspace_new("api", me=HUMAN)
        store.retire_workspace(self.db, "api")
        self.b.workspace_new("api", me=HUMAN)
        row = store.get_workspace(self.db, "api")
        self.assertIsNone(row["retired_at"])
        self.assertEqual(row["checkout"], r["path"])

    def test_a_bare_start_records_a_workspace_with_no_checkout(self):
        self.b.start(name="main", board=False)
        row = store.get_workspace(self.db, "main")
        self.assertIsNotNone(row)
        self.assertIsNone(row["checkout"])

    def test_a_bare_start_never_clears_a_worktree_workspaces_path(self):
        """Defence in depth behind the namespace rule: even if a bare name reached a
        worktree workspace's row, NULL is not written over a real checkout."""
        self.b.workspace_new("api", me=HUMAN)
        path = store.get_workspace(self.db, "api")["checkout"]
        self.b._record_workspace("api", None)
        self.assertEqual(store.get_workspace(self.db, "api")["checkout"], path)


if __name__ == "__main__":
    unittest.main()
