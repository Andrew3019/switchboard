"""D3 — `sb merge`: the return path off an isolated child's branch (spec §2.2).

REAL GIT, every test. This unit is git plumbing and nothing else: a fake that answered
"merged" or "conflict" on demand would pin the shape of the code and none of the
behaviour, and the failure modes that matter here — a conflict, a dirty tree, an
already-merged branch — are git's, not ours. So each test builds a throwaway repo in its
own tmp dir, with real worktrees on real branches, and asserts on what git ends up
holding. That also keeps it xdist-safe: nothing is shared between tests.

What is proven here and what is not:

  - **proven**: one child folded into the caller's branch; three folded incrementally, the
    later ones against the result; a real conflict detected and the merge LEFT IN PROGRESS
    for the integrator; the integrator spawned as the caller's child in the caller's
    checkout; nothing pushed to a real remote and no PR path reachable; a dirty checkout
    refused by name with no stash taken; `write-tracked` refused ON THE CHILD; a `shared`
    child having nothing to merge; a caller with no branch of its own refused.
  - **not proven here**: that a live integrator agent actually resolves the conflict and
    reports. That is a live multi-agent run, not a unit test — what a test can pin is that
    exactly one is spawned, told where the in-progress merge is, and that merging resumes
    against the resolved result (simulated here by resolving it by hand).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import store  # noqa: E402
from switchboard.broker import Broker  # noqa: E402

from test_workspace import FakeHerdr  # noqa: E402


class Fixture:
    """A real repo, real worktrees, real branches — and the store rows that say who is
    standing in which of them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        self.git("config", "commit.gpgsign", "false")
        self.write(self.repo, "shared.txt", "base\n")
        self.write(self.repo, "README.md", "base\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.base = self.head(self.repo)
        self.db = store.connect(path=self.root / "state.db")
        self.h = FakeHerdr(self.root / "worktrees")
        self.b = Broker(self.db, self.h, repo=self.repo)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    # -- git -------------------------------------------------------------

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=str(cwd or self.repo),
                              capture_output=True, text=True)

    def write(self, where: Path, name: str, text: str) -> None:
        (where / name).write_text(text)

    def commit(self, where: Path, name: str, text: str, msg: str = "c") -> None:
        self.write(where, name, text)
        self.git("add", "-A", cwd=where)
        self.git("commit", "-q", "-m", msg, cwd=where)

    def head(self, where: Path) -> str:
        return self.git("rev-parse", "HEAD", cwd=where).stdout.strip()

    def rev(self, branch: str) -> str:
        return self.git("rev-parse", branch).stdout.strip()

    def files(self, where: Path) -> set:
        return {p.name for p in where.iterdir() if p.is_file()}

    # -- agents ----------------------------------------------------------

    def _worktree(self, branch: str) -> Path:
        path = self.root / "wt" / branch
        r = self.git("worktree", "add", "-q", "-b", branch, str(path), "main")
        self.assertEqual(r.returncode, 0, r.stderr)
        return path

    def _agent(self, name: str, *, role: str, branch=None, path=None,
               parent=None, is_top: bool = False) -> str:
        store.create_agent(self.db, name=name, role=role, parent=parent,
                           workspace=name if branch else "scratch", branch=branch,
                           cwd=str(path) if path else str(self.repo),
                           pane_id=f"{name}:p1", is_top=is_top)
        return name

    def _lead(self, name: str = "lead-a") -> str:
        """The caller: a lead in a worktree of its own, on its own branch."""
        self.lead_path = self._worktree(name)
        return self._agent(name, role="lead", branch=name, path=self.lead_path)

    def _child(self, name: str, *, file: str, text: str, role: str = "worker",
               parent: str = "lead-a") -> str:
        """A finished `isolation=own` child: its own worktree, its own branch, one commit
        on it."""
        path = self._worktree(name)
        self.commit(path, file, text, msg=f"{name} work")
        return self._agent(name, role=role, branch=name, path=path, parent=parent)


class CleanMergeTest(Fixture, unittest.TestCase):
    """Objectives 1, 2, 4: one child, then several, into the caller's own checkout."""

    def test_one_child_folds_into_the_callers_branch(self):
        lead = self._lead()
        self._child("worker-one", file="one.txt", text="one\n")
        r = self.b.merge("worker-one", me=lead)
        self.assertEqual(r["status"], "merged")
        self.assertEqual(r["into"], lead)
        self.assertEqual(r["conflicts"], [])
        self.assertIsNone(r["integrator"])
        # The work is HERE — in the caller's own checkout, which is where the caller can
        # now see, test and finish it. No scratch clone: the path is the lead's own.
        self.assertIn("one.txt", self.files(self.lead_path))
        self.assertEqual(r["path"], str(self.lead_path))

    def test_three_children_merge_incrementally_each_against_the_result(self):
        """Not a collect-all-then-one-shot: the third is merged against a branch that
        already carries the first two."""
        lead = self._lead()
        for i, n in enumerate(("worker-one", "worker-two", "worker-three")):
            self._child(n, file=f"{n}.txt", text=f"{i}\n")
        self.b.merge("worker-one", me=lead)
        after_first = self.head(self.lead_path)
        self.b.merge("worker-two", me=lead)
        self.b.merge("worker-three", me=lead)
        self.assertLessEqual({"worker-one.txt", "worker-two.txt", "worker-three.txt"},
                             self.files(self.lead_path))
        # Each merge moved the caller's branch on, and the later ones started from where
        # the earlier ones left it.
        self.assertNotEqual(after_first, self.head(self.lead_path))
        self.assertEqual(self.rev(lead), self.head(self.lead_path))

    def test_a_branch_already_in_is_up_to_date_not_an_error(self):
        lead = self._lead()
        self._child("worker-one", file="one.txt", text="one\n")
        self.b.merge("worker-one", me=lead)
        before = self.head(self.lead_path)
        r = self.b.merge("worker-one", me=lead)
        self.assertEqual(r["status"], "up-to-date")
        self.assertEqual(self.head(self.lead_path), before)


class NeverLandsTest(Fixture, unittest.TestCase):
    """Objective 3, asserted NEGATIVELY and against a real remote: assembly is not
    landing."""

    def test_nothing_reaches_the_remote_and_main_does_not_move(self):
        origin = self.root / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        self.git("remote", "add", "origin", str(origin))
        self.git("push", "-q", "origin", "main")
        lead = self._lead()
        self._child("worker-one", file="one.txt", text="one\n")
        self.b.merge("worker-one", me=lead)
        refs = subprocess.run(["git", "ls-remote", str(origin)], capture_output=True,
                              text=True).stdout
        # The remote still has exactly the one branch it was given, at the commit it was
        # given — no lead branch, no child branch, and main where it was.
        self.assertEqual([ln.split()[1] for ln in refs.strip().splitlines()
                          if ln.split()[1].startswith("refs/heads/")],
                         ["refs/heads/main"])
        self.assertIn(self.base, refs)
        self.assertEqual(self.rev("main"), self.base)

    def test_no_push_and_no_pull_request_is_reachable_from_the_merge_path(self):
        """The source-level half of the same claim: the verb has no landing verb in it."""
        import inspect
        src = "\n".join(inspect.getsource(f) for f in (
            Broker.merge, Broker._merge_into, Broker._merge_blockers,
            Broker._conflicted, Broker._integrator_task))
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("#"))
        for forbidden in ('"push"', "'push'", "gh pr", "pr create", '"pull"'):
            self.assertNotIn(forbidden, code)


class DirtyTreeTest(Fixture, unittest.TestCase):
    """Objective 7: refuse, name what is uncommitted, and never stash."""

    def test_a_dirty_checkout_is_refused_by_name_and_nothing_is_stashed(self):
        lead = self._lead()
        self._child("worker-one", file="one.txt", text="one\n")
        self.write(self.lead_path, "shared.txt", "somebody's unfinished work\n")
        with self.assertRaises(ValueError) as cm:
            self.b.merge("worker-one", me=lead)
        self.assertIn("shared.txt", str(cm.exception))
        self.assertIn("does NOT stash", str(cm.exception))
        # Nothing merged, and nothing taken: the uncommitted edit is still sitting there
        # and the stash stack is empty.
        self.assertNotIn("one.txt", self.files(self.lead_path))
        self.assertEqual((self.lead_path / "shared.txt").read_text(),
                         "somebody's unfinished work\n")
        self.assertEqual(self.git("stash", "list", cwd=self.lead_path).stdout.strip(), "")

    def test_an_untracked_scratch_file_does_not_refuse_the_merge(self):
        """Tracked files only — a checkout with scratch in it is the normal state of a
        checkout, and a refusal that fires every time is one nobody can act on."""
        lead = self._lead()
        self._child("worker-one", file="one.txt", text="one\n")
        self.write(self.lead_path, "scratch.tmp", "notes\n")
        self.assertEqual(self.b.merge("worker-one", me=lead)["status"], "merged")


class ConflictTest(Fixture, unittest.TestCase):
    """Objectives 10-12: ONE integrator, for that one merge, then merging resumes."""

    def _conflicting_pair(self, lead: str):
        self._child("worker-one", file="shared.txt", text="one's answer\n")
        self._child("worker-two", file="shared.txt", text="two's answer\n")
        self.assertEqual(self.b.merge("worker-one", me=lead)["status"], "merged")
        return self.b.merge("worker-two", me=lead)

    def test_a_real_conflict_spawns_one_integrator_and_leaves_the_merge_in_progress(self):
        lead = self._lead()
        r = self._conflicting_pair(lead)
        self.assertEqual(r["status"], "conflict")
        self.assertEqual(r["conflicts"], ["shared.txt"])
        # ONE integrator, and it is the caller's own child, standing in the caller's
        # checkout — which is where the half-finished merge is.
        row = store.get_agent(self.db, r["integrator"])
        self.assertEqual(row["parent"], lead)
        self.assertEqual(row["cwd"], str(self.lead_path))
        self.assertEqual([a for a in self.h.live if a != lead], [r["integrator"]])
        # The merge is deliberately NOT aborted: that state is what is being resolved.
        self.assertTrue((self.lead_path / "shared.txt").read_text().count("<<<<<<<"))
        self.assertTrue(self.git("rev-parse", "-q", "--verify", "MERGE_HEAD",
                                 cwd=self.lead_path).stdout.strip())

    def test_the_integrator_is_told_where_the_merge_is_and_what_not_to_do(self):
        lead = self._lead()
        r = self._conflicting_pair(lead)
        task = " ".join(text for name, text in self.h.prompts
                        if name == r["integrator"])
        self.assertIn("shared.txt", task)
        self.assertIn(str(self.lead_path), task)
        self.assertIn("IN PROGRESS", task)
        self.assertIn("Do NOT push", task)

    def test_merging_resumes_against_the_resolved_result(self):
        """The loop objective 10 describes: the integrator finishes that merge, and the
        caller carries on with the next child against what it left behind. The resolution
        is done by hand here — a live agent doing it is a live run, not a unit test."""
        lead = self._lead()
        self._conflicting_pair(lead)
        self.write(self.lead_path, "shared.txt", "both answers\n")
        self.git("add", "-A", cwd=self.lead_path)
        self.git("commit", "-q", "-m", "resolved", cwd=self.lead_path)
        self._child("worker-three", file="three.txt", text="three\n")
        r = self.b.merge("worker-three", me=lead)
        self.assertEqual(r["status"], "merged")
        self.assertEqual((self.lead_path / "shared.txt").read_text(), "both answers\n")
        self.assertIn("three.txt", self.files(self.lead_path))

    def test_a_conflict_the_caller_cannot_spawn_for_is_aborted_not_left_behind(self):
        """A caller with no `spawn` has nobody to hand the conflict to, so the checkout is
        put back the way it was found rather than left half-merged for the next command to
        trip over."""
        path = self._worktree("worker-solo")
        me = self._agent("worker-solo", role="worker", branch="worker-solo", path=path)
        self.lead_path = path
        self._child("worker-one", file="shared.txt", text="one's answer\n",
                    parent=me)
        self._child("worker-two", file="shared.txt", text="two's answer\n",
                    parent=me)
        self.b.merge("worker-one", me=me)
        with self.assertRaises(ValueError) as cm:
            self.b.merge("worker-two", me=me)
        self.assertIn("shared.txt", str(cm.exception))
        self.assertIn("aborted", str(cm.exception))
        self.assertEqual(self.git("status", "--porcelain", cwd=path).stdout.strip(), "")


class RefusalTest(Fixture, unittest.TestCase):
    """Objectives 8-9 and the two "there is nothing here to merge" cases."""

    def test_write_tracked_is_checked_on_the_child_not_the_caller(self):
        lead = self._lead()
        self._child("researcher-notes", file="notes.md", text="read only\n",
                    role="researcher")
        self.assertFalse(self.b.holds_capability("researcher-notes", "write-tracked"))
        self.assertTrue(self.b.holds_capability(lead, "write-tracked"))
        with self.assertRaises(ValueError) as cm:
            self.b.merge("researcher-notes", me=lead)
        self.assertIn("researcher-notes", str(cm.exception))
        self.assertIn("write-tracked", str(cm.exception))
        self.assertNotIn("notes.md", self.files(self.lead_path))

    def test_one_refused_child_does_not_refuse_the_others_work_with_it(self):
        """Per-child, not per-batch."""
        lead = self._lead()
        self._child("researcher-notes", file="notes.md", text="read only\n",
                    role="researcher")
        self._child("worker-one", file="one.txt", text="one\n")
        with self.assertRaises(ValueError):
            self.b.merge("researcher-notes", me=lead)
        self.assertEqual(self.b.merge("worker-one", me=lead)["status"], "merged")

    def test_a_shared_child_has_no_branch_and_so_nothing_to_merge(self):
        lead = self._lead()
        self._agent("worker-tab", role="worker", path=self.lead_path, parent=lead)
        with self.assertRaises(ValueError) as cm:
            self.b.merge("worker-tab", me=lead)
        self.assertIn("no branch of its own", str(cm.exception))
        self.assertIn("shared", str(cm.exception))

    def test_an_unknown_child_is_named_not_guessed_at(self):
        lead = self._lead()
        with self.assertRaises(ValueError) as cm:
            self.b.merge("worker-nope", me=lead)
        self.assertIn("worker-nope", str(cm.exception))

    def test_a_caller_with_no_branch_of_its_own_is_refused(self):
        """The top's bare space is laid over the main checkout, so "merge into the caller's
        branch" would mean merging into main — which this verb never does."""
        top = self._agent("main", role="dispatcher", is_top=True)
        self._child("worker-one", file="one.txt", text="one\n", parent=top)
        with self.assertRaises(ValueError) as cm:
            self.b.merge("worker-one", me=top)
        self.assertIn("no branch of your own", str(cm.exception))
        self.assertEqual(self.rev("main"), self.base)

    def test_a_caller_standing_on_the_base_branch_is_refused(self):
        """A workspace CAN be named for the base branch — opening `main` attaches the
        primary checkout rather than forking it — and that is the one way a row's own
        branch is main."""
        me = self._agent("main-ws", role="lead", branch="main", path=self.repo)
        self._child("worker-one", file="one.txt", text="one\n", parent=me)
        with self.assertRaises(ValueError) as cm:
            self.b.merge("worker-one", me=me)
        self.assertIn("never writes to the base branch", str(cm.exception))
        self.assertEqual(self.rev("main"), self.base)

    def test_a_checkout_that_moved_under_the_row_is_refused(self):
        lead = self._lead()
        self._child("worker-one", file="one.txt", text="one\n")
        self.git("checkout", "-q", "--detach", cwd=self.lead_path)
        with self.assertRaises(ValueError) as cm:
            self.b.merge("worker-one", me=lead)
        self.assertIn("detached HEAD", str(cm.exception))


class CommandTest(Fixture, unittest.TestCase):
    """The verb exists on the CLI and is taught to agents."""

    def test_sb_merge_takes_one_child(self):
        from switchboard.cli import build_parser
        args = build_parser().parse_args(["merge", "worker-one"])
        self.assertEqual((args.cmd, args.child), ("merge", "worker-one"))
        with self.assertRaises(SystemExit):       # one child at a time, not a batch
            build_parser().parse_args(["merge", "worker-one", "worker-two"])

    def test_the_protocol_teaches_it(self):
        from switchboard import config
        self.assertIn("sb merge", config.protocol(self.repo))


if __name__ == "__main__":
    unittest.main()
