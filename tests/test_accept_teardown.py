"""The one guard in `acceptance/accept.py` that stands between a test run and the fleet.

`accept.py` is not part of the suite and must not join it — it spawns real agents. This
tests the single pure function in it that decides whether a herdr workspace may be closed,
because that decision is the one place in the whole repo that calls `herdr workspace close`,
and herdr closes a workspace's whole worktree family when the workspace is a repo's primary
checkout (`notes/herdr-close-mechanism.md`). The guard is worth a test for the same reason
`sb workspace close`'s refusals are: the interesting question is never whether it closes,
it is what stops it.

Real directories, no fakes: the check is about paths on disk, and `realpath` is half of what
it does — on macOS a `$TMPDIR` under `/var` resolves to `/private/var`, and a guard that
compared strings would refuse everything it created.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("accept", REPO / "acceptance" / "accept.py")
accept = importlib.util.module_from_spec(_spec)
# In sys.modules before it is executed: `accept.py` defines dataclasses, and a dataclass
# resolves its own module out of sys.modules while it is being built.
sys.modules["accept"] = accept
_spec.loader.exec_module(accept)


class WorkspaceIsOursTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "sbabc123-w1"
        (self.root / "sub").mkdir(parents=True)
        self.addCleanup(self.tmp.cleanup)

    def test_a_checkout_inside_the_clone_is_ours(self):
        wt = {"repo_root": str(self.root), "checkout_path": str(self.root / "sub")}
        self.assertTrue(accept.workspace_is_ours(wt, [self.root]))

    def test_the_live_primary_checkout_is_refused(self):
        """The exact shape of the outage: a repo_root that is not the clone's.

        A substring selection would have taken this — `/Users/andrew/Code/switchboard`
        contains no clone path, but a workspace naming BOTH could, and it is the primary
        checkout whose close takes every worktree of the repo with it.
        """
        wt = {"repo_root": "/Users/andrew/Code/switchboard",
              "checkout_path": str(self.root / "sub")}
        self.assertFalse(accept.workspace_is_ours(wt, [self.root]))

    def test_a_workspace_herdr_reports_no_paths_for_is_refused(self):
        """No evidence is not the same as good evidence, and defaults to refusing."""
        self.assertFalse(accept.workspace_is_ours({}, [self.root]))
        self.assertFalse(accept.workspace_is_ours({"repo_root": ""}, [self.root]))


class TeardownCallsTheGuardTest(unittest.TestCase):
    """The guard is only worth anything if the teardown actually consults it.

    So this drives `Clone._close_workspaces` itself with herdr's `workspace list` faked and
    its `workspace close` recorded rather than run — the one command this repo may never
    issue for real — and asserts on which ids were spent.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.clone = accept.Clone(root, root, "sbabc123-w1", "main", _SilentLog())
        self.clone.path.mkdir(parents=True)
        self.closed: list[str] = []
        self.listing: list[dict] = []
        real = accept.herdr_call
        self.addCleanup(setattr, accept, "herdr_call", real)
        accept.herdr_call = self._fake_herdr

    def _fake_herdr(self, *args: str):
        if args[:2] == ("workspace", "list"):
            return {"workspaces": self.listing}
        if args[:2] == ("workspace", "close"):
            self.closed.append(args[2])
            return {}
        raise AssertionError(f"unexpected herdr call: {args}")

    def test_it_closes_its_own_workspace(self):
        self.listing = [{"workspace_id": "w1", "label": "ours",
                         "worktree": {"repo_root": str(self.clone.path),
                                      "checkout_path": str(self.clone.path)}}]
        self.clone._close_workspaces()
        self.assertEqual(self.closed, ["w1"])

    def test_it_refuses_a_workspace_that_only_looks_like_ours(self):
        """Selected by the substring match, refused by the guard — nothing is closed.

        `repo_root` is a live primary checkout whose path merely CONTAINS the clone's, the
        way a stray worktree of it would; closing that is what the outage was.
        """
        self.listing = [{"workspace_id": "w9", "label": "not ours",
                         "worktree": {"repo_root": "/Users/andrew/Code/switchboard",
                                      "checkout_path": f"{self.clone.path}-elsewhere"}}]
        self.clone._close_workspaces()
        self.assertEqual(self.closed, [])


class _SilentLog:
    def write(self, *_args, **_kw):
        pass


if __name__ == "__main__":
    unittest.main()
