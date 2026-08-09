"""Repro: a recorded checkout path that resolves to the worktree but is not git's
string for it. checkout_verdict says OK (it resolves both sides); _deregister compares
strings, finds no match, and reports "unregistered" without removing anything."""
import sys, os, unittest
from pathlib import Path
sys.path.insert(0, "/Users/andrew/.herdr/worktrees/switchboard/teardown-fix")
sys.path.insert(0, "/Users/andrew/.herdr/worktrees/switchboard/teardown-fix/tests")

from switchboard import live, store
from switchboard.broker import HUMAN
from test_workspace_list import Harness


class T(Harness, unittest.TestCase):
    def test_unresolved_recorded_path(self):
        real = self.worktree("api")            # git's own string, fully resolved
        # An equivalent path for the same directory, via a symlink — exactly the shape
        # /tmp -> /private/tmp gives you on macOS.
        link = self.root / "link"
        link.symlink_to(self.root / "wt")
        alias = str(link / "api")
        self.assertTrue(Path(alias).is_dir())
        self.assertNotEqual(alias, real)
        store.record_workspace(self.db, "api", alias)

        self.assertEqual(store.checkout_verdict(alias, cwd=self.repo), store.CHECKOUT_OK)
        r = self.b.workspace_close("api", me=HUMAN)
        print("RESULT:", r)
        print("still on disk:", Path(real).is_dir())
        print("still registered:", [w["path"] for w in self.b._worktrees()])
        print("row:", dict(store.get_workspace(self.db, "api")))


unittest.main()
