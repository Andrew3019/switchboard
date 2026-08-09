"""`sb workspace close` on a checkout that still exists — the one destructive command.

Almost everything here tests a REFUSAL, and that is the right shape for it: this is the
only command in switchboard whose failure mode is unrecoverable, and the interesting
question is never "does it delete a worktree" but "what stops it". So there is a test per
thing that stops it — a row, a process, a scan that could not be made, the primary
checkout, an unfilled store, a mark somebody holds, work git can see, ignored content
nobody has looked at — and a test for the two orderings that make a refusal cheap: the
gate runs before anything is closed, and it runs AGAIN after the panes are down, which is
the evaluation that authorises the deletion.

The bare path gets its own class because it is its own path. Sharing the general gate was
a real bug, not an untidiness: scoped to the primary clone it would refuse every bare
workspace forever, on the strength of whoever else is sitting in that directory.

Real git, and a real `ps`; the process scan is the one thing faked, since a test cannot
put a process in a temporary directory and be sure of it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import live, store  # noqa: E402
from switchboard.broker import HUMAN  # noqa: E402
from switchboard.herdr import HerdrError  # noqa: E402
from test_workspace_list import Harness  # noqa: E402


class CloseHarness(Harness):
    """A worktree workspace recorded the way an attach would have recorded it."""

    def space(self, name: str = "api", *, commit: bool = False) -> str:
        path = self.worktree(name, commit=commit)
        store.record_workspace(self.db, name, path)
        return path

    def agent(self, name: str, *, workspace: str, cwd: str, pane: str = None,
              state: str = "done"):
        self.row(name, workspace=workspace, branch=workspace, cwd=cwd, state=state)
        if pane:
            store.update_agent(self.db, name, pane_id=pane)
            self.h.panes.add(pane)

    def machine(self, *procs: "live.Proc"):
        """What the scan finds, and a process table that agrees those pids exist.

        Both halves, because the gate reads both: a pid the process table no longer knows
        has exited, and a process that has exited is not in the directory. Faking only the
        scan would test that rule rather than the containment this is usually about.
        """
        live.scan = lambda *a, **kw: list(procs)
        parents = {os.getpid(): os.getppid(), os.getppid(): 1, 1: 0}
        parents.update({p.pid: 1 for p in procs if p.pid not in parents})
        self.b._parents = lambda: parents

    def registered(self) -> list[str]:
        return [wt["path"] for wt in self.b._worktrees()]

    def mark(self, name: str):
        return store.get_workspace(self.db, name)["retiring"]


class GateTest(CloseHarness, unittest.TestCase):
    """Nothing is touched until both halves of the gate agree the directory is empty."""

    def test_an_unfinished_row_under_the_checkout_refuses(self):
        path = self.space()
        self.agent("worker", workspace="api", cwd=f"{path}/switchboard", state="working")
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn("worker", str(e.exception))
        self.assertIn(path, self.registered())

    def test_a_row_whose_workspace_id_is_somebody_elses_still_counts(self):
        """The gate is scoped to the DIRECTORY. Two workspace ids can sit over one
        checkout, so enumerating one of them says nothing about who else is in there."""
        path = self.space()
        self.row("stranger", workspace="something-else", branch="something-else",
                 cwd=path, state="working")
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn("stranger", str(e.exception))

    def test_the_callers_own_row_does_not_count_against_it(self):
        """An agent told to close the workspace it works in is recorded under that
        checkout and is not finished, because it is running this command."""
        path = self.space()
        self.agent("api-lead", workspace="api", cwd=path, state="working")
        self.b.workspace_close("api", me="api-lead")
        self.assertNotIn(path, self.registered())

    def test_a_sibling_whose_name_is_a_string_prefix_is_not_under_this_checkout(self):
        """Worktrees are siblings in one directory and their names nest as strings, so a
        prefix match would gate the shorter name forever on the longer one's rows."""
        path = self.space("api")
        sibling = self.worktree("api-2")
        self.row("worker", workspace="api-2", branch="api-2", cwd=f"{sibling}/sub",
                 state="working")
        self.b.workspace_close("api", me=HUMAN)
        self.assertNotIn(path, self.registered())

    def test_a_process_in_the_directory_refuses_though_no_row_knows_about_it(self):
        """A human with an editor open has no `agents` row to be finished, and this is one
        of the two places a person who never appears in the store gets to say no."""
        path = self.space()
        self.machine(live.Proc(4242, "vim", f"{path}/switchboard"))
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn("vim", str(e.exception))
        self.assertIn(path, self.registered())

    def test_a_scan_that_could_not_be_made_refuses_because_unknown_is_not_empty(self):
        """The branch that decides the outcome when herdr has restarted and forgotten:
        `agent list` cannot fail, so it answers an empty success and every row reads
        finished. A silent fall-through to "nothing live" here is what turns a confidently
        wrong record into a deletion."""
        path = self.space()
        live.scan = lambda *a, **kw: None
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn("could not be asked", str(e.exception))
        self.assertIn(path, self.registered())

    def test_our_own_process_tree_does_not_count_against_us(self):
        """Including the scanner itself, which is our own child and reports its own cwd —
        a caller standing in the checkout would otherwise find one live process every
        time and refuse forever."""
        path = self.space()
        self.machine(live.Proc(os.getpid(), "python", path),
                     live.Proc(os.getppid(), "zsh", path))
        self.b.workspace_close("api", me=HUMAN)
        self.assertNotIn(path, self.registered())

    def test_a_process_that_has_since_exited_is_not_in_the_directory(self):
        """Which is how `lsof` stops reporting ITSELF against us: it is our own child,
        sitting in our cwd, and it has exited by the time the process table is read."""
        path = self.space()
        live.scan = lambda *a, **kw: [live.Proc(4242, "lsof", path)]
        self.b._parents = lambda: {os.getpid(): os.getppid(), os.getppid(): 1, 1: 0}
        self.b.workspace_close("api", me=HUMAN)
        self.assertNotIn(path, self.registered())

    def test_a_process_table_that_will_not_answer_costs_a_refusal(self):
        """The safe direction: we can prove only two pids are ours without it."""
        path = self.space()
        live.scan = lambda *a, **kw: [live.Proc(4242, "vim", path)]
        self.b._parents = lambda: None
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn("vim", str(e.exception))

    def test_the_primary_checkout_is_refused_by_a_rule_of_its_own(self):
        """A record can legitimately point at the primary clone, and git only refuses at
        the very last step — by which time the inventory has listed the human's own files
        and the panes are closed."""
        store.record_workspace(self.db, "primary", str(self.repo))
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("primary", me=HUMAN)
        self.assertIn("primary working tree", str(e.exception))
        self.assertIn(str(self.repo), self.registered())

    def test_a_store_whose_fill_never_completed_refuses(self):
        """An unfilled table and a table with no workspaces are the same empty query, and
        acting on the second while looking at the first is how every real workspace comes
        to read as unrecorded."""
        self.space()
        self.db.execute("DELETE FROM meta WHERE key='backfill:workspaces'")
        self.db.commit()
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn("never been filled in", str(e.exception))

    def test_a_path_that_is_not_a_worktree_of_this_repo_refuses(self):
        (self.root / "elsewhere").mkdir()
        store.record_workspace(self.db, "odd", str(self.root / "elsewhere"))
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("odd", me=HUMAN)
        self.assertIn("cannot tell", str(e.exception))


class CleanlinessTest(CloseHarness, unittest.TestCase):
    """Two tiers. Plain porcelain is the wrong question: it does not list ignored files,
    and the removal deletes them anyway."""

    def setUp(self):
        super().setUp()
        (self.repo / ".gitignore").write_text(".env\nCLAUDE.md\n")
        self.git("add", ".gitignore")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "ig")

    def test_a_tracked_modification_refuses_outright(self):
        path = Path(self.space())
        (path / ".gitignore").write_text("changed\n")
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn("modified or untracked", str(e.exception))
        self.assertIn(str(path), self.registered())

    def test_an_untracked_file_refuses_outright(self):
        path = Path(self.space())
        (path / "notes.md").write_text("mine")
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn("modified or untracked", str(e.exception))

    def test_switchboards_own_furniture_needs_no_confirmation(self):
        """Unlinking one of its symlinks leaves the target standing in the main checkout,
        and a prompt that lists them every time is a prompt people learn to dismiss."""
        path = Path(self.space())
        (self.repo / "CLAUDE.md").write_text("hello")
        (path / "CLAUDE.md").symlink_to(self.repo / "CLAUDE.md")
        self.b.workspace_close("api", me=HUMAN)
        self.assertNotIn(str(path), self.registered())
        self.assertTrue((self.repo / "CLAUDE.md").exists())     # the target survives

    def test_ignored_content_nobody_planted_is_inventoried_and_not_deleted(self):
        path = Path(self.space())
        (path / ".env").write_text("SECRET=1")
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn(".env", str(e.exception))                 # what, not just how many
        self.assertIn("--yes", str(e.exception))
        self.assertTrue((path / ".env").exists())
        self.assertIsNone(self.mark("api"))

    def test_the_confirmation_deletes_it_with_the_checkout(self):
        path = Path(self.space())
        (path / ".env").write_text("SECRET=1")
        self.b.workspace_close("api", me=HUMAN, confirm=True)
        self.assertNotIn(str(path), self.registered())
        self.assertFalse(path.exists())


class OrderingTest(CloseHarness, unittest.TestCase):
    """Check, then stop, then re-confirm, then delete — and why it is in that order."""

    def test_a_refusal_closes_no_panes(self):
        """"Stop, then check" left the panes closed, the command reporting failure and
        nothing retired: the person loses their panes and gets nothing for them."""
        path = self.space()
        self.agent("api-lead", workspace="api", cwd=path, pane="w9:p1")
        self.row("worker", workspace="api", branch="api", cwd=path, state="working")
        with self.assertRaises(ValueError):
            self.b.workspace_close("api", me=HUMAN)
        self.assertEqual(self.h.closed, [])
        self.assertIn("w9:p1", self.h.panes)

    def test_the_re_confirmation_catches_what_arrived_during_the_stop_step(self):
        path = self.space()
        self.agent("api-lead", workspace="api", cwd=path, pane="w9:p1")
        self.machine(live.Proc(4242, "vim", path))
        answers = [[], [live.Proc(4242, "vim", path)]]
        live.scan = lambda *a, **kw: answers.pop(0) if answers else []
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn("vim", str(e.exception))
        self.assertIn(path, self.registered())                  # nothing was deleted
        self.assertIsNone(self.mark("api"))                     # and no mark left behind
        self.assertEqual(self.h.closed, ["w9:p1"])              # the panes did go, though

    def test_the_mark_is_claimed_before_anything_is_destroyed(self):
        """So a command that dies midway is resumable rather than a workspace whose
        directory is gone and whose rows still read live."""
        self.space()
        seen = []
        deregister = self.b._deregister
        self.b._deregister = lambda p: (seen.append(self.mark("api")), deregister(p))[1]
        self.b.workspace_close("api", me="tidy-up")
        self.assertEqual(seen, ["tidy-up"])

    def test_a_refusal_after_the_claim_clears_the_mark(self):
        """Only a crash may leave a mark set. A refusal that left one would lock a live
        workspace's name out of itself over a command that did nothing."""
        path = self.space()
        self.machine(live.Proc(4242, "vim", path))
        answers = [[], [live.Proc(4242, "vim", path)]]
        live.scan = lambda *a, **kw: answers.pop(0) if answers else []
        with self.assertRaises(ValueError):
            self.b.workspace_close("api", me=HUMAN)
        self.assertIsNone(self.mark("api"))

    def crash_in_the_window(self, boom: BaseException):
        """Close a workspace whose deregistration dies the way a crash dies."""
        path = self.space()

        def crash(_):
            raise boom
        self.b._deregister = crash
        with self.assertRaises(type(boom)):
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn(path, self.registered())              # and nothing was deleted

    def test_a_hung_git_clears_the_mark_though_it_is_no_refusal(self):
        """The regression. Releasing on `ValueError` alone was a rule about the SHAPE of
        the exception, and a hung `git worktree remove` does not have that shape: the
        timeout came out of `_deregister`, the mark stayed set, and the name was left
        needing a resume that the rule below would then never offer it."""
        self.crash_in_the_window(subprocess.TimeoutExpired("git", 5))
        self.assertIsNone(self.mark("api"))

    def test_ctrl_c_while_the_checkout_comes_down_clears_the_mark(self):
        """A `BaseException`, and the likeliest crash of all: a person watching a
        destructive command take too long."""
        self.crash_in_the_window(KeyboardInterrupt())
        self.assertIsNone(self.mark("api"))

    def test_a_pane_that_will_not_close_refuses_before_anything_is_deleted(self):
        path = self.space()
        self.agent("api-lead", workspace="api", cwd=path, pane="w9:p1")

        def refuse(pane):
            raise HerdrError("herdr_unavailable", "no answer")
        self.h.close_pane = refuse
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn("would not close", str(e.exception))
        self.assertIn(path, self.registered())
        self.assertIsNone(self.mark("api"))

    def test_a_pane_herdr_has_already_lost_is_this_close_having_happened(self):
        path = self.space()
        self.agent("api-lead", workspace="api", cwd=path, pane="w9:p1")

        def gone(pane):
            raise HerdrError("pane_not_found", "no such pane")
        self.h.close_pane = gone
        r = self.b.workspace_close("api", me=HUMAN)
        self.assertEqual(r["closed"], ["api-lead"])
        self.assertNotIn(path, self.registered())


class DeleteTest(CloseHarness, unittest.TestCase):
    """What the last step actually does, once it is allowed to."""

    def test_it_removes_exactly_the_named_worktree_and_never_prunes(self):
        """One bare `git worktree prune` deregisters every prunable checkout in the
        repository, including one another agent has just gated."""
        path = self.space("api")
        other = self.worktree("other")
        r = self.b.workspace_close("api", me=HUMAN)
        self.assertEqual(r["worktree"], "removed")
        self.assertNotIn(path, self.registered())
        self.assertIn(other, self.registered())

    def test_it_closes_the_workspaces_panes_and_forgets_them(self):
        path = self.space()
        self.agent("api-lead", workspace="api", cwd=path, pane="w9:p1")
        self.agent("api-worker", workspace="api", cwd=path, pane="w9:p2")
        r = self.b.workspace_close("api", me=HUMAN)
        self.assertEqual(sorted(r["closed"]), ["api-lead", "api-worker"])
        self.assertEqual(sorted(self.h.closed), ["w9:p1", "w9:p2"])
        self.assertIsNone(store.get_agent(self.db, "api-lead")["pane_id"])

    def test_an_unmerged_branch_simply_stays(self):
        """`-d`, never `-D`: an unmerged branch left standing is a far cheaper failure
        than losing commits, and it stays forever by design."""
        path = self.space("own-work", commit=True)
        r = self.b.workspace_close("own-work", me=HUMAN)
        self.assertFalse(r["branch_deleted"])
        self.assertNotIn(path, self.registered())
        self.assertIn("own-work", self.git("branch").stdout)

    def test_the_workspace_is_retired_and_its_recorded_path_cleared(self):
        """The command has just deleted that directory; a row still pointing at it starts
        every later question from a path we know is gone."""
        self.space()
        self.b.workspace_close("api", me=HUMAN)
        row = store.get_workspace(self.db, "api")
        self.assertTrue(row["retired_at"])
        self.assertIsNone(row["checkout"])
        self.assertIsNone(row["retiring"])


class BarePathTest(CloseHarness, unittest.TestCase):
    """A workspace with no checkout of its own: retire it, and that is the whole thing."""

    def bare(self, name: str = "main-2"):
        store.record_workspace(self.db, name, None)

    def test_it_is_retired_and_no_git_runs_at_all(self):
        self.bare()
        r = self.b.workspace_close("main-2", me=HUMAN)
        self.assertEqual(r["kind"], "bare")
        self.assertIsNone(r["branch"])
        self.assertEqual(r["worktree"], "none")
        self.assertTrue(store.get_workspace(self.db, "main-2")["retired_at"])

    def test_it_takes_none_of_the_general_paths_steps(self):
        """The bug this path exists for. The general gate is scoped to a checkout path,
        and a bare workspace's path is the primary clone — where the human sits, where
        every other bare orchestrator sits, and where the agent that typed the command
        usually sits. Shared, it would refuse `main-2` because `main-3` is live in a
        directory nobody is deleting, forever."""
        self.bare("main-2")
        self.bare("main-3")
        self.row("main-3", workspace="main-3", cwd=str(self.repo), state="working")
        self.machine(live.Proc(4242, "vim", str(self.repo)))
        (self.repo / "uncommitted.md").write_text("the human's own work")
        r = self.b.workspace_close("main-2", me=HUMAN)
        self.assertEqual(r["kind"], "bare")
        self.assertTrue((self.repo / "uncommitted.md").exists())
        self.assertIn(str(self.repo), self.registered())

    def test_its_own_unfinished_rows_still_hold_it(self):
        """The gate the first draft had, scoped to the case it was right for."""
        self.bare()
        self.row("main-2", workspace="main-2", cwd=str(self.repo), state="working")
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("main-2", me=HUMAN)
        self.assertIn("main-2", str(e.exception))
        self.assertIsNone(store.get_workspace(self.db, "main-2")["retired_at"])

    def test_its_own_panes_come_down_with_it(self):
        self.bare()
        self.row("main-2", workspace="main-2", cwd=str(self.repo), state="done")
        store.update_agent(self.db, "main-2", pane_id="w1:p1")
        self.h.panes.add("w1:p1")
        r = self.b.workspace_close("main-2", me=HUMAN)
        self.assertEqual(r["closed"], ["main-2"])
        self.assertEqual(self.h.closed, ["w1:p1"])

    def test_a_bare_workspace_is_never_asked_about_the_primary_checkout(self):
        """Bare workspaces record no path precisely so that the primary-checkout rule —
        and every other rule about a directory — never applies to them."""
        self.bare("main")
        self.assertEqual(self.b.workspace_close("main", me=HUMAN)["kind"], "bare")


class CrashedMarkTest(CloseHarness, unittest.TestCase):
    """A mark is never stolen and never expires; a person takes it over, or nobody does."""

    def held(self, name: str = "api", owner: str = "other-agent", *, state="working"):
        path = self.space(name)
        self.row(owner, workspace="elsewhere", cwd=str(self.root), state=state)
        store.claim_retiring(self.db, name, owner)
        return path

    def test_a_live_owner_refuses_and_offers_no_way_round_it(self):
        self.held()
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn("other-agent", str(e.exception))
        self.assertNotIn("--resume", str(e.exception))

    def test_an_owner_confirmed_gone_is_disclosed_and_names_resume(self):
        """Wave 2's trust layer is what makes that answer worth acting on, and this is the
        first place the destructive command spends it."""
        self.held(state="failed")
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn("confirmed gone", str(e.exception))
        self.assertIn("--resume", str(e.exception))

    def test_an_owner_we_cannot_confirm_either_way_still_refuses_but_offers_the_flag(self):
        """Not confirmed gone is not confirmed live, and only the second closes the flag
        off. Walling the name up is not the safe direction — see the human-owned mark
        below for where that road ends."""
        path = self.space()
        store.claim_retiring(self.db, "api", "vanished-agent")   # no row to ask about
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn("vanished-agent", str(e.exception))
        self.assertIn("cannot be confirmed either way", str(e.exception))
        self.assertIn("--resume", str(e.exception))
        self.assertIn(path, self.registered())                   # and refused all the same

    def test_resume_takes_over_a_dead_owners_mark_and_runs_the_whole_command(self):
        path = self.held(state="failed")
        r = self.b.workspace_close("api", me="tidy-up", resume=True)
        self.assertNotIn(path, self.registered())
        self.assertTrue(r["branch_deleted"])

    def test_resume_still_re_runs_the_gate_rather_than_inheriting_a_verdict(self):
        """It is not a repair verb: a crashed invocation's own findings are exactly what
        nobody should inherit."""
        path = self.held(state="failed")
        self.row("worker", workspace="api", branch="api", cwd=path, state="working")
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me="tidy-up", resume=True)
        self.assertIn("worker", str(e.exception))

    def test_resume_against_a_live_owner_refuses_like_any_other_close(self):
        """Permission to take over from a corpse, not permission to overrule a winner."""
        self.held()
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me="tidy-up", resume=True)
        self.assertIn("other-agent", str(e.exception))
        self.assertEqual(self.mark("api"), "other-agent")

    def test_a_mark_a_human_left_behind_is_reachable(self):
        """The regression, and the brick it comes from. A person has no `agents` row, so
        `_owner_gone` can only ever answer "cannot tell" about one — and under the old
        rule that read as a live owner, which offered no flag. Crash a teardown the human
        was running and the mark was set forever, with `workspace_new` and `--workspace`
        refusing the name too: no verb reached the row again and the way back was editing
        the store by hand."""
        path = self.space()
        store.claim_retiring(self.db, "api", HUMAN)
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn("--resume", str(e.exception))             # a door, not a wall
        self.assertIn(path, self.registered())
        self.b.workspace_close("api", me=HUMAN, resume=True)
        self.assertNotIn(path, self.registered())

    def test_the_refusal_always_says_who_holds_the_mark_and_since_when(self):
        """Whether to wait, to retry or to go and look is the reader's decision, and those
        two facts are what it turns on — so they are in every one of these messages, not
        only the ones that end in a flag."""
        self.held()                                             # a live owner: no flag
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("api", me=HUMAN)
        self.assertIn("other-agent", str(e.exception))
        self.assertIn("ago", str(e.exception))

    def test_two_invocations_arriving_together_resolve_rather_than_both_proceeding(self):
        """`claim_retiring`'s `rowcount` is the arbiter, and the claim IS the write: there
        is no separate read for a second invocation to race against."""
        self.space()
        self.assertTrue(store.claim_retiring(self.db, "api", "first"))
        self.assertFalse(store.claim_retiring(self.db, "api", "second"))


class PathIdentityTest(CloseHarness, unittest.TestCase):
    """"The same directory" is one question, and it used to have two answers."""

    def alias(self, name: str = "api") -> tuple[str, str]:
        """The recorded path and git's own, for one checkout reached two ways.

        A symlinked parent, which is not a contrivance: `/tmp` and `/var` are exactly
        this on macOS, so anything recorded under `$TMPDIR` has the shape already.
        """
        real = self.worktree(name)
        (self.root / "link").symlink_to(self.root / "wt")
        alias = str(self.root / "link" / name)
        store.record_workspace(self.db, name, alias)
        return alias, real

    def test_a_differently_spelled_path_is_the_same_checkout_and_is_really_removed(self):
        """The regression. Re-validation resolved both sides and said CHECKOUT_OK, so the
        whole destructive route ran; the deregistration compared strings, matched nothing,
        called that "already unregistered" — success — and returned having removed
        nothing, with the branch deleted and the row retired over a checkout still on
        disk and still registered."""
        alias, real = self.alias()
        self.assertEqual(store.checkout_verdict(alias, cwd=self.repo), store.CHECKOUT_OK)
        r = self.b.workspace_close("api", me=HUMAN)
        self.assertEqual(r["worktree"], "removed")
        self.assertFalse(Path(real).is_dir())
        self.assertNotIn(real, self.registered())

    def test_a_sibling_reached_through_the_alias_is_still_not_this_checkout(self):
        """Resolving both sides is not loosening the comparison: `api-2` reached through
        the same symlink is a different directory and stays registered."""
        self.alias("api")
        sibling = self.worktree("api-2")
        self.b.workspace_close("api", me=HUMAN)
        self.assertIn(sibling, self.registered())


class OrphanTest(CloseHarness, unittest.TestCase):
    """A checkout only git knows about — listed by `sb workspace list`, and until now
    listed and nothing else."""

    def test_a_checkout_with_no_row_anywhere_can_still_be_closed_by_name(self):
        """The regression. The `workspaces` table is backfilled from `agents`, so a
        checkout nobody was ever recorded in never got a row, and the close refused on the
        strength of that — on exactly the workspaces the listing's three-source union
        exists to surface, and exactly the ones with nothing in them to lose."""
        path = self.worktree("orphan")
        self.assertIsNone(store.get_workspace(self.db, "orphan"))
        r = self.b.workspace_close("orphan", me=HUMAN)
        self.assertEqual(r["kind"], "worktree")
        self.assertNotIn(path, self.registered())
        self.assertFalse(Path(path).is_dir())

    def test_it_goes_through_the_same_gate_as_anything_else(self):
        """Recording the path gets the name to the front door and no further: nothing
        about an orphan makes it cheaper to destroy than a workspace with rows."""
        path = self.worktree("orphan")
        self.machine(live.Proc(4242, "vim", f"{path}/switchboard"))
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("orphan", me=HUMAN)
        self.assertIn("vim", str(e.exception))
        self.assertIn(path, self.registered())

    def test_the_primary_checkout_is_no_more_adoptable_than_it_is_closable(self):
        """`main` is a worktree git reports, so it is adoptable by name — and then it
        meets the rule it was always going to meet."""
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("main", me=HUMAN)
        self.assertIn("primary working tree", str(e.exception))
        self.assertIn(str(self.repo), self.registered())

    def test_a_name_git_does_not_know_either_still_refuses(self):
        with self.assertRaises(ValueError) as e:
            self.b.workspace_close("nothing-like-this", me=HUMAN)
        self.assertIn("nothing here to close", str(e.exception))


if __name__ == "__main__":
    unittest.main()
