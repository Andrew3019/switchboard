"""Repro: anything that is not a ValueError inside the destructive window strands the
retiring mark, and a mark owned by the human can never be taken over."""
import subprocess as sp
import sys, unittest
from pathlib import Path
sys.path.insert(0, "/Users/andrew/.herdr/worktrees/switchboard/teardown-fix")
sys.path.insert(0, "/Users/andrew/.herdr/worktrees/switchboard/teardown-fix/tests")

from switchboard import store
from switchboard.broker import HUMAN
from test_workspace_list import Harness


class T(Harness, unittest.TestCase):
    def test_timeout_strands_the_mark_and_resume_never_works(self):
        path = self.worktree("api")
        store.record_workspace(self.db, "api", path)

        # `git worktree remove` hanging: _deregister calls subprocess.run with a timeout
        # and catches nothing, so TimeoutExpired leaves the try-block by a door the
        # `except ValueError` rollback does not cover.
        real = self.b._deregister
        def boom(checkout):
            raise sp.TimeoutExpired(["git", "worktree", "remove"], 30)
        self.b._deregister = boom
        with self.assertRaises(sp.TimeoutExpired):
            self.b.workspace_close("api", me=HUMAN)
        self.b._deregister = real

        row = store.get_workspace(self.db, "api")
        print("mark after the crash:", row["retiring"])

        for flag in (False, True):
            try:
                self.b.workspace_close("api", me=HUMAN, resume=flag)
                print("resume=%s: SUCCEEDED" % flag)
            except ValueError as e:
                print("resume=%s: refused -> %s" % (flag, e))
        # And by another agent, too.
        self.row("someone", workspace="api", branch="api", cwd=path, state="done")
        try:
            self.b.workspace_close("api", me="someone", resume=True)
            print("other caller with --resume: SUCCEEDED")
        except ValueError as e:
            print("other caller with --resume: refused -> %s" % e)


unittest.main()
