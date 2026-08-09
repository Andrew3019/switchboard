"""Repro: (a) the checkout left behind by the alias case is then unreachable by close;
(b) a registered checkout with no store row refuses forever."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, "/Users/andrew/.herdr/worktrees/switchboard/teardown-fix")
sys.path.insert(0, "/Users/andrew/.herdr/worktrees/switchboard/teardown-fix/tests")

from switchboard import store
from switchboard.broker import HUMAN
from test_workspace_list import Harness


class T(Harness, unittest.TestCase):
    def test_stranded_checkout_is_then_unreachable(self):
        real = self.worktree("api")
        link = self.root / "link"; link.symlink_to(self.root / "wt")
        store.record_workspace(self.db, "api", str(link / "api"))
        self.b.workspace_close("api", me=HUMAN)
        again = self.b.workspace_close("api", me=HUMAN)
        print("second close:", again)
        print("checkout still on disk:", Path(real).is_dir())

    def test_an_orphan_checkout_with_no_row_cannot_be_closed(self):
        self.worktree("orphan")
        print("listed:", {n: (w["verdict"], w["sources"])
                          for n, w in self.listed().items()})
        try:
            self.b.workspace_close("orphan", me=HUMAN)
            print("closed it")
        except ValueError as e:
            print("refused ->", e)


unittest.main()
