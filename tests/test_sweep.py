"""The automatic worktree sweep: the four decisions it is allowed to make.

These are not confidence tests. The sweep was proved end to end in an isolated clone with
thirteen real worktrees, real commits, a real `lsof` and three real boards; what is pinned
here is the handful of rules a later edit could quietly change without any of that
noticing.

Real git throughout, including a real bare remote for the pushed case — "landed" is a
question about what git actually says, and a fake git answering it would be pinning the
fake.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
import unittest
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import store, sweep  # noqa: E402
from test_workspace_list import Harness  # noqa: E402

DAY = 86400


def no_identity_to_guess() -> dict:
    """The environment of a machine git can auto-detect no committer on.

    The Linux CI runner is one: no global or system config, and a hostname with no
    domain in it, which git calls bogus and refuses to build an address from. macOS has
    a `.local` hostname to work from, guesses happily, and that is why the macOS leg of
    the matrix stayed green. `user.useConfigOnly` asks for that state on any machine:
    it is the switch that turns off the guessing, and it leaves the repository's own
    config as the only place an identity can come from, which is exactly the question.
    """
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_") and k != "EMAIL"}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="user.useConfigOnly",
               GIT_CONFIG_VALUE_0="true")
    return env


class SweepHarness(Harness):
    """The list harness, plus commits with dates on them and a remote to push to."""

    def setUp(self):
        super().setUp()
        self.origin = self.root / "origin.git"
        self.reader = sweep.reader(self.repo)

    def remote(self):
        """A real bare `origin` with `main` on it."""
        self.git("init", "-q", "--bare", str(self.origin), cwd=self.root)
        self.git("remote", "add", "origin", str(self.origin))
        self.git("push", "-q", "origin", "main:main")
        self.git("fetch", "-q", "origin")

    def commit(self, path: str, *, cwd, message: str, age: float = 3 * DAY) -> None:
        """A real commit, dated. The committer date is the one the sweep reads."""
        import os
        import subprocess
        when = f"{int(time.time() - age)} +0000"
        f = Path(cwd) / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"{message}\n")
        self.git("add", "-A", cwd=cwd)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "-m", message],
                       cwd=str(cwd), capture_output=True, text=True,
                       env={**os.environ, "GIT_AUTHOR_DATE": when,
                            "GIT_COMMITTER_DATE": when})

    def branched(self, name: str, path: str, message: str, age: float = 3 * DAY) -> str:
        """A worktree on its own branch with one commit on it. Returns the checkout."""
        checkout = self.worktree(name)
        self.commit(path, cwd=checkout, message=message, age=age)
        return checkout

    def merge(self, branch: str, *, env: Optional[dict] = None) -> None:
        """Merge `branch` into the base, and refuse to carry on if git did not.

        `Harness.git` returns the failure rather than raising it, so a merge that never
        happened looks from here exactly like a landing check that cannot see one — and
        that is how it read for a day, as a platform-fragile check rather than a fixture
        that quietly did nothing (`test_a_merge_lands_where_git_can_guess_no_identity`).
        A fixture that skips a step in silence is worse than one that breaks: it moves
        the blame onto the code under test.
        """
        out = self.git("merge", "-q", "--no-ff", "-m", f"merge {branch}", branch,
                       env=env)
        if out.returncode != 0:
            said = (out.stderr or out.stdout).strip().splitlines()
            raise AssertionError(f"the fixture could not merge {branch!r}: "
                                 f"{said[-1] if said else 'git said nothing'}")

    def stranded(self, branch: str) -> list[str]:
        base = sweep.base_ref(self.reader)
        return sweep.stranded(self.reader, sweep.tip_of(self.reader, branch), base)


class LandingTest(SweepHarness, unittest.TestCase):
    """**Landed means merged OR pushed** — and merged means the work is in `main`, not
    that this branch's commits are ancestors of it.

    Three worktrees in the 2026-08-16 census had their PR merged and their content in
    `main`, and read as unmerged to an ancestry check because the merge squashed or
    rebased them. A sweep gated on ancestry refuses exactly the branches that are safest
    to remove.
    """

    def test_a_pushed_branch_is_landed_though_nothing_merged_it(self):
        """The bar is recoverable from origin. A PR is encouraged and not required."""
        self.remote()
        self.branched("pushed", "switchboard/thing.py", "a feature nobody merged")
        self.git("push", "-q", "origin", "pushed:pushed")
        self.git("fetch", "-q", "origin")
        self.assertEqual(self.stranded("pushed"), [], "a pushed branch is recoverable")

    def test_a_branch_merged_into_main_is_landed(self):
        self.branched("merged", "switchboard/thing.py", "a feature that got merged")
        self.merge("merged")
        self.assertEqual(self.stranded("merged"), [])

    def test_a_merge_lands_where_git_can_guess_no_identity(self):
        """The Linux CI failure of 2026-08-16, pinned where it happened — in the fixture.

        The check was never the fragile part and never ran on a merged branch at all:
        the runner could auto-detect no committer, so the fixture's own `git merge`
        refused to write a commit, and a branch that was never merged read as stranded.
        The repo the harness builds carries an identity of its own now, so a merge here
        is a merge on any machine. Same test as the one above, with the guessing off.
        """
        self.branched("merged", "switchboard/thing.py", "a feature that got merged")
        self.merge("merged", env=no_identity_to_guess())
        self.assertEqual(self.stranded("merged"), [])

    def test_a_squashed_branch_is_landed_though_its_commits_are_ancestors_of_nothing(self):
        """The census case. The squash keeps the subject in its body and nothing else, so
        the subject is what is matched — see `sweep.stranded`, rule 3."""
        subject = "a feature that was squashed on the way in"
        self.branched("squashed", "switchboard/thing.py", subject)
        Path(self.repo, "other.py").write_text("the squashed version\n")
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                 "-m", f"squash: bring it in (#99)\n\n* {subject}")
        self.assertEqual(self.stranded("squashed"), [])

    def test_a_commit_that_is_nowhere_else_is_stranded(self):
        """The one answer that holds a worktree open, and the only one that matters to get
        right in this direction: a false landed deletes a checkout."""
        self.branched("mine-alone", "switchboard/thing.py", "a feature nobody has seen")
        self.assertEqual(len(self.stranded("mine-alone")), 1)

    def test_a_short_subject_is_never_matched(self):
        """`min_subject`. A branch whose commit says "wip" must not land itself by
        matching any of the hundred other commits that say "wip"."""
        self.branched("terse", "switchboard/thing.py", "wip")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                 "--allow-empty", "-m", "wip")
        self.assertEqual(len(self.stranded("terse")), 1)


class DocsOnlyTest(unittest.TestCase):
    """**Unpushed commits block deletion — unless they are docs only**, decided by PATH.

    Pure, because the rule is: no content is read, no judgement is made, and that is the
    property worth pinning against a later edit that decides to be cleverer.
    """

    def test_markdown_anywhere_and_the_documentation_directories_are_docs(self):
        self.assertTrue(sweep.docs_only(["notes/a.md", "README.md", "design/b.md",
                                         "learnings/c.txt", "research/d/e.json"]))

    def test_one_code_file_among_them_is_enough_to_block(self):
        self.assertFalse(sweep.docs_only(["notes/a.md", "switchboard/broker.py"]))

    def test_design_truth_is_never_docs(self):
        """The carve-out. It is the only trusted document in the repo and only Andrew
        edits it, so an unpushed change to it is never a note somebody can regenerate."""
        # Named through the config rather than spelled out: a quoted literal of that
        # filename reads as a citation to `tests/test_design_truth_refs.py`.
        truth = sweep.DOCS_NEVER[0]
        self.assertFalse(sweep.docs_only([truth]))
        self.assertTrue(sweep.docs_only([f"design/{truth}-notes.md"]))


class BothClocksTest(unittest.TestCase):
    """**"Over a day old" must satisfy both clocks.** Either one being recent holds it."""

    def test_a_recent_commit_holds_a_worktree_whose_agents_are_long_gone(self):
        now = time.time()
        self.assertIsNotNone(sweep.too_recent(int(now - 60), int(now - 9 * DAY), now))

    def test_recent_agent_activity_holds_a_worktree_with_an_old_commit(self):
        now = time.time()
        self.assertIsNotNone(sweep.too_recent(int(now - 9 * DAY), int(now - 60), now))

    def test_both_quiet_for_a_day_is_the_only_way_through(self):
        now = time.time()
        self.assertIsNone(sweep.too_recent(int(now - 2 * DAY), int(now - 2 * DAY), now))


class OneSweepPerSlotTest(unittest.TestCase):
    """**Exactly one board sweeps.** Every agent's pane opens with a board beside it, so a
    fleet of twenty crosses :30 twenty times at once."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        (self.repo / ".git").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_second_board_to_reach_a_slot_does_not_get_it(self):
        slot = sweep.slot_of(time.time())
        self.assertTrue(sweep.claim(slot, cwd=self.repo))
        self.assertFalse(sweep.claim(slot, cwd=self.repo))
        self.assertTrue(sweep.claim(slot + 1, cwd=self.repo))

    def test_a_clock_that_went_backwards_sweeps_nothing_until_it_catches_up(self):
        slot = sweep.slot_of(time.time())
        self.assertTrue(sweep.claim(slot, cwd=self.repo))
        self.assertFalse(sweep.claim(slot - 5, cwd=self.repo))


class SweptSetTest(SweepHarness, unittest.TestCase):
    """The whole policy over one fleet: what goes, what stays, and why it says so.

    A dry run, because what is being pinned is the classification. The deletion itself is
    `workspace_close`'s, which has its own tests and its own gates, and it was exercised
    for real in the clone.
    """

    def space(self, name: str, path: str, *, state: str = "done",
              age: float = 3 * DAY) -> None:
        store.record_workspace(self.db, name, path)
        self.row(f"w-{name}", workspace=name, branch=name, cwd=path, state=state)
        when = int(time.time() - age)
        self.db.execute(
            "UPDATE agents SET created_at=?, ended_at=? WHERE name=?",
            (when, None if state == "working" else when, f"w-{name}"))

    def held(self, out: dict) -> dict:
        return {h["name"]: h["reason"] for h in out["held"]}

    def test_the_swept_set_is_landed_or_docs_only_and_quiet_on_both_clocks(self):
        cases = {
            "landed": ("switchboard/a.py", "a feature that got merged in"),
            "docs": ("notes/a.md", "notes: a finding worth nothing later"),
            "code": ("switchboard/b.py", "a feature that never left this machine"),
            "truth": (sweep.DOCS_NEVER[0], "truth: an amendment nobody pushed"),
            "young": ("switchboard/c.py", "a feature merged in a moment ago"),
            "busy": ("switchboard/d.py", "a feature whose agent is still going"),
            "dirty": ("switchboard/e.py", "a feature left beside uncommitted work"),
        }
        for name, (path, message) in cases.items():
            age = 0 if name == "young" else 3 * DAY
            checkout = self.branched(name, path, message, age=age)
            if name in ("landed", "young", "busy", "dirty"):
                self.merge(name)
            self.space(name, checkout, state="working" if name == "busy" else "done",
                       age=0 if name == "young" else 3 * DAY)
        Path(self.root / "wt" / "dirty" / "left-behind.md").write_text("unsaved\n")

        out = self.b.sweep(dry_run=True)
        self.assertEqual(sorted(out["swept"]), ["docs", "landed"])
        held = self.held(out)
        self.assertIn("not docs", held["code"])
        self.assertIn(sweep.DOCS_NEVER[0], held["truth"])
        self.assertIn("under the 24h floor", held["young"])
        self.assertIn("still recorded as working", held["busy"])
        self.assertIn("modified or untracked", held["dirty"])

    def test_nothing_is_swept_on_an_unknown_answer(self):
        """Unknown is not empty, and a sweep is the one loop that acts unattended."""
        checkout = self.branched("opaque", "switchboard/a.py", "a feature that merged")
        self.merge("opaque")
        self.space("opaque", checkout)
        import switchboard.live as live_mod
        live_mod.scan = lambda *a, **kw: None     # the machine would not answer
        out = self.b.sweep(dry_run=True)
        self.assertEqual(out["swept"], [])
        self.assertIn("unknown is not empty", self.held(out)["opaque"])


class GoneRowsTest(SweepHarness, unittest.TestCase):
    """A stale workspace has two shapes, and the sweep only ever had one of them.

    92 of the 277 rows in the 2026-08-16 census were `absent` — the row and its branch
    outlived the directory — and the sweep's first line skipped every verdict that was
    not `ok`. So the cheapest case in the whole store, the one with nothing left to
    decide, was the one case nothing automatic could reach: each was a `sb workspace
    close <name>` somebody typed by hand (#77).
    """

    def gone(self, name: str, *, commit: bool = False) -> str:
        """A real linked checkout, recorded, then deleted out from under the record."""
        path = self.worktree(name, commit=commit)
        store.record_workspace(self.db, name, path)
        shutil.rmtree(path)
        return path

    def held(self, out: dict) -> dict:
        return {h["name"]: h["reason"] for h in out["held"]}

    def test_a_row_whose_directory_is_gone_is_swept_and_taken_off_the_books(self):
        """Not a dry run: what was missing was the bookkeeping, so the bookkeeping is
        what this asserts — the registration gone, the branch gone, the row retired."""
        path = self.gone("stale")
        out = self.b.sweep()
        self.assertEqual(out["swept"], ["stale"])
        self.assertNotIn(path, [wt["path"] for wt in self.b._worktrees()])
        row = store.get_workspace(self.db, "stale")
        self.assertTrue(row["retired_at"])
        self.assertIsNone(row["checkout"])

    def test_an_unfinished_row_under_the_gone_path_still_holds_it(self):
        """The one rule that survives the directory: a deleted checkout does not retract
        a claim that somebody is working under it."""
        path = self.gone("stale")
        self.row("w-stale", workspace="stale", branch="stale", cwd=path, state="working")
        out = self.b.sweep()
        self.assertEqual(out["swept"], [])
        self.assertIn("still recorded as working", self.held(out)["stale"])
        self.assertIsNone(store.get_workspace(self.db, "stale")["retired_at"])

    def test_bare_and_retired_rows_are_still_never_looked_at(self):
        """Both exemptions are choices. Closing a bare space would retire an
        orchestrator's space out from under a sweep aimed at agents; a retired row is
        already closed, and nothing in switchboard deletes a workspace row."""
        store.record_workspace(self.db, "orchestrator", None)
        store.record_workspace(self.db, "done-already", str(self.root / "wt" / "old"))
        store.retire_workspace(self.db, "done-already")
        out = self.b.sweep()
        self.assertEqual(out["swept"], [])
        self.assertEqual(out["held"], [])
        self.assertEqual(out["looked"], 0)
