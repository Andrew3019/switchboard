"""The `plans` plugin — the state model, before any step can move.

Eleven tests, pinning decisions rather than buying confidence. Everything sb owns — the
parser built from the declaration, the state directory, the `--json` envelope — is tested
in `test_plugins.py`, so these run through `cli.main` for the same reason the other
shipped-plugin tests do and then assert only what this plugin decided:

1. A plan round-trips: what `create` makes is what `show` and `list` render, both empty
   and with its steps already in it. Both halves of `create` are first class.
2. Ids are monotonic and never reused, across plans and across steps — a spawn prompt
   citing `s-2` has to stay true even after somebody hand-deletes a row.
3. `list` is scoped to this worktree, matched on the checkout path.
4. The workspace is resolved once, at `create`, and a branch change in the same checkout
   does not move it — the key is the workspace, and the branch is not the workspace.
5. A checkout that is no workspace says so rather than being filed under a guess, and an
   sb that cannot be reached is a different answer again — `workspace_from` carries which,
   and resolution is bounded so a wedged sb cannot hold the plans lock for a minute.
6. The changelog accumulates and carries the reason the agent supplied, and a write that
   would drop an entry — or the plan holding it — is refused. That record is what the
   analysis pass reads.
7. An unreadable file is refused rather than replaced, by every verb.
8. So is one malformed inside its plans list — duplicate ids included, plans and steps
   alike, and a file from a newer plugin.
9. A refusal reaches a machine reader: the reason is in `data`, not only in `human`.
10. The state lock is held while a command writes, which is what makes two commands
   touching different steps safe.

Unproven, and not provable here: the real two-process race (test 10 asserts the lock is
held around the write, not that two `sb` processes interleave correctly — provoking that
would be an endurance run against a real store); and that anybody keeps a plan honest once
the job is running, which is a workflow question and not a code one.

`plans` ships available but not enabled, like `todo`, so every test turns it on in the one
line a repo would write to adopt it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from switchboard import plugins  # noqa: E402
from switchboard import store  # noqa: E402

from test_fork_lock import _held  # noqa: E402
from test_shipped_plugins import ShippedSandbox  # noqa: E402


class PlansSandbox(ShippedSandbox):
    """The sandbox, plus the two things the workspace resolver needs to be real.

    `bin/sb` beside the copied `defaults/` is not a fixture trick: it is the first branch of
    `_sb()` — a plugin shipped inside a checkout asks that checkout's build — and pointing
    it at this repo's real `bin/sb` is what makes the shell-out run the code under test
    against the sandbox's own store rather than whatever is installed on the machine.
    """

    def setUp(self) -> None:
        super().setUp()
        (self.sw / "plugins.toml").write_text('enabled = ["plans"]\n')
        root = Path(self.tmp.name)
        (root / "bin").symlink_to(Path(__file__).resolve().parent.parent / "bin")

    def workspace(self, name: str, checkout: Path, *, agent: str = "") -> None:
        """A workspace row, the way `sb` writes one, so the resolver has a real answer.

        With `agent`, an agent row standing in it too — which is the resolver's FIRST
        question and the normal path, since a lead is what creates a plan.
        """
        db = store.connect(self.repo)
        store.record_workspace(db, name, str(checkout))
        if agent:
            store.create_agent(db, name=agent, role="lead", workspace=name,
                               cwd=str(checkout))
        db.close()

    def _dir(self) -> Path:
        return plugins.state_root("repo", self.repo) / "plans"

    def _file(self) -> Path:
        return self._dir() / "plans.json"

    def _doc(self) -> dict:
        return json.loads(self._file().read_text())


class PlansTest(PlansSandbox):

    def test_a_plan_round_trips_empty_and_with_steps(self):
        """`create` with nothing makes a plan; `create` with steps makes the same plan with
        them already in it. The design says defining a plan upfront is the point, and that
        a lead may also start before the work is shaped — neither is the special case."""
        empty = self.data("plugin", "plans", "create")
        self.assertEqual(empty["id"], "p-1")
        self.assertEqual(empty["steps"], [])

        made = self.data("plugin", "plans", "create", "build", "the", "plugin",
                         "--step", "write it", "--step", "test it",
                         "--note", "PR1 only", "--reason", "the job is shaped")
        self.assertEqual(made["id"], "p-2")
        self.assertEqual([s["id"] for s in made["steps"]], ["s-1", "s-2"])
        self.assertEqual(made["steps"][0],
                         {"id": "s-1", "name": "write it", "progress": "open",
                          "owner": None, "tries": 1, "notes": [], "deps": [],
                          "checkpoints": []})
        self.assertEqual(made["notes"][0]["text"], "PR1 only")

        shown = self.ok("plugin", "plans", "show", "p-2")
        for expected in ("p-2", "build the plugin", "s-1", "s-2", "write it", "test it",
                         "the job is shaped"):
            self.assertIn(expected, shown)

        listed = self.ok("plugin", "plans", "list")
        self.assertIn("p-1", listed)
        self.assertIn("p-2", listed)
        self.assertIn("2 steps", listed)

    def test_list_shows_the_plans_on_this_worktree(self):
        """A plan belongs to one worktree and from inside it the others are invisible. The
        plans of another checkout are still in the file, and `--all` is how you see them."""
        self.ok("plugin", "plans", "create", "here")
        doc = self._doc()
        doc["plans"][0]["checkout"] = "/somewhere/else"
        self._file().write_text(json.dumps(doc))
        self.assertEqual(self.data("plugin", "plans", "list"), [])
        self.assertEqual([p["id"] for p in self.data("plugin", "plans", "list", "--all")],
                         ["p-1"])

    def test_the_workspace_is_resolved_once_and_survives_a_branch_change(self):
        """The key is the WORKSPACE, which is what the board groups by and what a later PR
        reads to decide a worktree is gone — not the branch, which moves under a checkout
        that has not. Filed once at `create`, and neither recomputed nor re-attached: a
        `git checkout -b` in the same directory used to make `list` go blind to the plan
        that was made there, with nothing recording that it had.
        """
        self.workspace("ws-1", self.repo, agent="lead-1")
        self.as_agent("lead-1")         # the normal path: a lead makes the plan
        made = self.data("plugin", "plans", "create", "a job", "--step", "write it")
        self.assertEqual(made["workspace"], "ws-1")
        self.assertEqual(made["workspace_from"], "agent")
        self.assertEqual(Path(made["checkout"]).resolve(), self.repo.resolve())

        self.ok("plugin", "plans", "create", "a second job")
        subprocess.run(["git", "checkout", "-q", "-b", "fixups"], cwd=self.repo, check=True)

        self.assertEqual([p["id"] for p in self.data("plugin", "plans", "list")],
                         ["p-1", "p-2"])
        self.assertEqual(self.data("plugin", "plans", "show", "p-1")["workspace"], "ws-1")
        self.assertEqual(self.data("plugin", "plans", "create", "after the branch change")
                         ["workspace"], "ws-1")

    def test_a_checkout_that_is_no_workspace_says_so(self):
        """No workspace row for this checkout, so there is no name to store. Written down
        as null and rendered as itself: a plausible-looking wrong key — the branch, the
        directory — would read to PR4 as a worktree that has gone."""
        made = self.data("plugin", "plans", "create", "in a plain clone")
        self.assertIsNone(made["workspace"])
        self.assertEqual(made["workspace_from"], "none")
        self.assertIn("(no workspace)", self.ok("plugin", "plans", "show", "p-1"))
        self.assertEqual([p["id"] for p in self.data("plugin", "plans", "list")], ["p-1"])

    def test_an_unanswerable_sb_is_not_the_same_fact_as_no_workspace(self):
        """Both store a null workspace, and PR4 reads that field to decide a plan is
        abandoned. `none` is sb saying this checkout belongs to nowhere; `unavailable` is
        sb not saying anything, at one instant, about a job that may be perfectly healthy —
        and nothing recomputes the field afterwards, so the distinction has to be written
        down when the plan is made or it is never recoverable.

        The whole resolution is bounded, too: it happens with the plans lock held, so an
        sb that has wedged must cost seconds rather than wedge every other plans command in
        the repo behind it.
        """
        (Path(self.tmp.name) / "bin").unlink()          # no build beside the plugin
        real = shutil.which
        with mock.patch("shutil.which",                 # and none on PATH either
                        lambda name, *a, **k: None if name == "sb" else real(name, *a, **k)):
            started = time.monotonic()
            made = self.data("plugin", "plans", "create", "during an outage")
        self.assertLess(time.monotonic() - started, 10)

        self.assertIsNone(made["workspace"])
        self.assertEqual(made["workspace_from"], "unavailable")
        self.assertIn("workspace unresolved", made["changelog"][0]["detail"])
        self.assertIn("(unresolved)", self.ok("plugin", "plans", "show", "p-1"))

    def test_ids_are_monotonic_and_never_reused(self):
        """One step counter for the whole file, not one per plan: two plans on a worktree
        would otherwise both have an `s-1`, and "your step is s-1" would name nothing. A
        hand-deleted plan must not free either number — a changelog entry citing it stays
        true for the life of the repo."""
        self.ok("plugin", "plans", "create", "one", "--step", "a", "--step", "b")
        self.ok("plugin", "plans", "create", "two", "--step", "c")
        self.assertEqual([s["id"] for s in self.data("plugin", "plans", "show", "p-2")
                          ["steps"]], ["s-3"])

        doc = self._doc()
        doc["plans"] = [p for p in doc["plans"] if p["id"] != "p-2"]
        self._file().write_text(json.dumps(doc))

        made = self.data("plugin", "plans", "create", "three", "--step", "d")
        self.assertEqual(made["id"], "p-3")
        self.assertEqual([s["id"] for s in made["steps"]], ["s-4"])

    def test_the_changelog_is_append_only_and_carries_the_reason(self):
        """Written by the command, with the reason the agent supplied. A plan is reshaped
        as the job runs, and without this the file keeps only the final shape."""
        self.as_agent("w1")
        made = self.data("plugin", "plans", "create", "a job",
                         "--step", "a", "--reason", "investigation landed")
        (entry,) = self.data("plugin", "plans", "changelog", made["id"])
        self.assertEqual(entry["by"], "w1")
        self.assertEqual(entry["action"], "create")
        self.assertEqual(entry["reason"], "investigation landed")
        self.assertIn("s-1", entry["detail"])

        # The single write is where append-only is enforced, so that a future verb that
        # rewrites a plan wholesale fails loudly instead of quietly losing the story. Both
        # halves: an edited changelog, and the easier loss — the whole plan not written back.
        mod = _plans()
        for wreck, expected in ((lambda d: d["plans"][0].update(changelog=[]), "append-only"),
                                (lambda d: d.update(plans=[]), "never erased")):
            with self.subTest(expected=expected):
                doc, seal = mod._read(self._dir())
                wreck(doc)
                with self.assertRaises(ValueError) as caught:
                    mod._write(self._dir(), doc, seal)
                self.assertIn(expected, str(caught.exception))
        self.assertEqual(len(self._doc()["plans"][0]["changelog"]), 1)

    def test_an_unreadable_file_is_refused_rather_than_replaced(self):
        """Starting over on a corrupt file would silently replace every plan in the repo on
        the next `create`, and the records are the whole reason for keeping them.

        Every verb, and the message names the path and says the file is safe: a refusal
        that only says no sends a human looking for a bug in sb instead of at the file."""
        self.ok("plugin", "plans", "create", "a job")
        self._file().write_text("{ this is not json")
        for argv in (("create", "another"), ("list",), ("show", "p-1"), ("changelog", "p-1")):
            with self.subTest(verb=argv[0]):
                code, _, err = self.sb("plugin", "plans", *argv)
                self.assertEqual(code, 1)
                self.assertIn("not readable JSON", err)
                self.assertIn("plans.json", err)
                self.assertIn("will overwrite", err)
        self.assertEqual(self._file().read_text(), "{ this is not json")

    def test_a_file_malformed_inside_the_plans_list_is_refused_by_name(self):
        """Checked all the way down, not just at the top level — and the seal is why, not
        tidiness. It is keyed on the plan id, so two plans sharing one (or one with none)
        collapse to a single entry and `_write`'s drop check passes over the plan whose
        changelog is no longer in it. Refusing here is refusing before anything is written.
        """
        twins = [{"id": "s-1", "name": "one"}, {"id": "s-1", "name": "a twin"}]
        wrecks = {"holds a str where a plan should be": {"plans": ["hello"]},
                  "holds a NoneType where a plan should be": {"plans": [None]},
                  "holds a plan with no usable id": {"plans": [{"title": "nameless"}]},
                  "holds two plans called p-1": {"plans": [{"id": "p-1"}, {"id": "1"}]},
                  "whose steps are not a list": {"plans": [{"id": "p-1", "steps": "nope"}]},
                  "whose changelog is not a list": {"plans": [{"id": "p-1",
                                                               "changelog": {}}]},
                  # A twin step takes a tick meant for the other and neither says so; a
                  # step with no id cannot be ticked at all. Both are PR2's bug to inherit.
                  "holds two steps called s-1": {"plans": [{"id": "p-1", "steps": twins}]},
                  "with no usable id": {"plans": [{"id": "p-1",
                                                   "steps": [{"name": "nameless"}]}]},
                  "was written by a newer plans plugin": {"format": 99, "plans": []}}
        for expected, doc in wrecks.items():
            with self.subTest(expected=expected):
                self._dir().mkdir(parents=True, exist_ok=True)
                self._file().write_text(json.dumps(doc))
                code, _, err = self.sb("plugin", "plans", "create", "should not land")
                self.assertEqual(code, 1)
                self.assertIn(expected, err)
                self.assertEqual(json.loads(self._file().read_text()), doc)

    def test_a_refusal_reaches_a_machine_reader_too(self):
        """sb prints `data` under `--json` and not `human`, so a reason that lives only in
        `human` is a reason for a person and for nobody else. PR4 and PR8 shell out for
        exactly these answers, and `ok:false` with a null payload gives them nothing to
        render or log."""
        self.ok("plugin", "plans", "create", "a job")
        for argv, expected in ((("show", "p-9"), "the highest is p-1"),
                               (("changelog", "banana"), "is not a plan id")):
            with self.subTest(verb=argv[0]):
                code, out, _ = self.sb("plugin", "plans", *argv, "--json")
                self.assertEqual(code, 1)
                self.assertIn(expected, json.loads(out)["data"]["error"])

        # The cap covers `--reason` too — the one field every later verb carries into the
        # changelog, and the one an agent is most likely to write an essay into.
        code, out, _ = self.sb("plugin", "plans", "create", "a job",
                               "--reason", "x" * 3000, "--json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["data"]["length"], 3000)

    def test_the_state_lock_is_held_while_a_command_writes(self):
        """Two commands touching different steps are safe because each reads, changes and
        writes with the lock held — so the whole-file rewrite cannot lose the other's
        write. Asserted at the write, on a fresh fd, which conflicts with sb's own even
        inside this process."""
        held, real = [], os.replace

        def watched(src, dst):
            # Watched at `os.replace` rather than at the plugin's own `_write`: sb imports
            # a plugin afresh on every invocation, so a patch on the module object is
            # already stale by the time the command under test runs.
            if str(dst).endswith("plans.json"):
                held.append(_held(self._dir() / ".lock"))
            real(src, dst)

        with mock.patch("os.replace", watched):
            self.ok("plugin", "plans", "create", "a job")
            self.ok("plugin", "plans", "create", "another job")
        self.assertEqual(held, [True, True])
        self.assertEqual([p["id"] for p in self.data("plugin", "plans", "list")],
                         ["p-1", "p-2"])


def _plans():
    """The loaded plugin module, by the name sb imported it under."""
    return sys.modules[plugins._MODULE_PREFIX + "plans"]


if __name__ == "__main__":
    unittest.main()
