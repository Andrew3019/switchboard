"""Concurrent spawns and the one git write they cannot both do.

`git worktree add -b <name> origin/main` records the new branch's upstream in
`.git/config`, and git takes `.git/config.lock` to do it with `O_EXCL` and no timeout — so
of two spawns issued at the same moment, one fails outright and its agent never exists.
Measured before the fix, on a clone of this repo: twenty rounds of two concurrent adds,
twenty losers; and through `sb delegate`, two dead spawns in six.

These three pin the shape of the fix rather than the race itself. The race lives in git,
and a test that forked real worktrees to provoke it would be a slow endurance run — what
is worth holding still is that the create is serialised, that NOTHING ELSE in the fork is,
and that a lock nobody releases costs a wait rather than a spawn.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import broker as broker_mod, store  # noqa: E402
from switchboard.broker import Broker  # noqa: E402


def _held(lock: Path) -> bool:
    """Is somebody holding the fork lock right now? Asked on a fresh fd, which conflicts
    with the broker's own even inside this process — flock is per open file description."""
    if not lock.exists():
        return False
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


class ForkHerdr:
    """Just enough herdr to answer `worktree create`, and to say what it saw while it ran."""

    def __init__(self, root: Path, lock: Path):
        self.root, self.lock = root, lock
        self.created: list[str] = []
        self.locked_during: list[bool] = []

    def create_worktree(self, branch: str, *, base: str = "main", cwd=None, label=None):
        self.created.append(branch)
        self.locked_during.append(_held(self.lock))
        path = self.root / branch
        path.mkdir(parents=True, exist_ok=True)
        return {"workspace": {"workspace_id": "w1", "label": branch,
                              "worktree": {"checkout_path": str(path), "branch": branch}},
                "root_pane": {"pane_id": "w1:p1"}}


class ForkLockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        run = lambda *a: subprocess.run(a, cwd=self.repo, capture_output=True)  # noqa: E731
        run("git", "init", "-q", "-b", "main")
        run("git", "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-q", "--allow-empty", "-m", "x")
        self.lock = store.store_dir(self.repo) / "fork.lock"
        self.db = store.connect(path=Path(self.tmp.name) / "state.db")
        self.h = ForkHerdr(Path(self.tmp.name) / "worktrees", self.lock)
        self.b = Broker(self.db, self.h, repo=self.repo)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_the_worktree_create_is_the_one_step_nobody_else_may_be_doing(self):
        """The whole fix: while a fork is creating, no second fork can be."""
        self.b._attach_workspace("api", base="main")
        self.assertEqual(self.h.created, ["api"])
        self.assertEqual(self.h.locked_during, [True])
        self.assertFalse(_held(self.lock))          # and it is let go afterwards

    def test_the_fetch_before_it_is_not_serialised(self):
        """Scope, which is half the point: a fork's slow part is the network, and six
        spawns must still do that at the same time. If the lock ever creeps outward to
        cover `_fork_base`, a six-way fan-out starts paying six fetches end to end."""
        seen = []
        real = self.b._fork_base
        self.b._fork_base = lambda base: (seen.append(_held(self.lock)), real(base))[1]
        self.b._attach_workspace("api", base="main")
        self.assertEqual(seen, [False])

    def test_a_lock_nobody_releases_costs_a_wait_and_then_the_fork_happens_anyway(self):
        """A spawn that cannot get its turn must not die — the failure this whole change
        exists to remove. It waits, gives up waiting, and forks regardless."""
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)              # a holder that never returns
        try:
            with mock.patch.object(broker_mod, "FORK_LOCK_WAIT", 0.2):
                r = self.b._attach_workspace("api", base="main")
        finally:
            os.close(fd)
        self.assertEqual(r["workspace"], "api")     # it forked
        self.assertEqual(self.h.created, ["api"])
        kinds = [e["kind"] for e in store.recent_events(self.db)]
        self.assertIn("fork_lock_timeout", kinds)   # and said so


if __name__ == "__main__":
    unittest.main()
