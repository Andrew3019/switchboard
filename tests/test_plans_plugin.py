"""The `plans` plugin — the state model, before any step can move.

Four tests, pinning decisions rather than buying confidence. Everything sb owns — the
parser built from the declaration, the state directory, the `--json` envelope — is tested
in `test_plugins.py`, so these run through `cli.main` for the same reason the other
shipped-plugin tests do and then assert only what this plugin decided:

1. A plan round-trips: what `create` makes is what `show` and `list` render, both empty
   and with its steps already in it. Both halves of `create` are first class.
2. Ids are monotonic and never reused, across plans and across steps — a spawn prompt
   citing `s-2` has to stay true even after somebody hand-deletes a row.
3. The changelog accumulates and carries the reason the agent supplied, and a write that
   would drop an entry is refused. That record is what the analysis pass reads.
4. The state lock is held while a command writes, which is what makes two commands
   touching different steps safe.

Unproven, and not provable here: the real two-process race (test 4 asserts the lock is
held around the write, not that two `sb` processes interleave correctly — provoking that
would be an endurance run against a real store); and that anybody keeps a plan honest once
the job is running, which is a workflow question and not a code one.

`plans` ships available but not enabled, like `todo`, so every test turns it on in the one
line a repo would write to adopt it.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from switchboard import plugins  # noqa: E402

from test_fork_lock import _held  # noqa: E402
from test_shipped_plugins import ShippedSandbox  # noqa: E402


class PlansSandbox(ShippedSandbox):

    def setUp(self) -> None:
        super().setUp()
        (self.sw / "plugins.toml").write_text('enabled = ["plans"]\n')

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
        self.assertEqual(made["workspace"], "main")     # the sandbox repo's branch
        self.assertEqual(made["notes"][0]["text"], "PR1 only")

        shown = self.ok("plugin", "plans", "show", "p-2")
        for expected in ("p-2", "build the plugin", "s-1", "s-2", "write it", "test it",
                         "main", "the job is shaped"):
            self.assertIn(expected, shown)

        listed = self.ok("plugin", "plans", "list")
        self.assertIn("p-1", listed)
        self.assertIn("p-2", listed)
        self.assertIn("2 steps", listed)

    def test_list_shows_the_plans_on_this_worktree(self):
        """A plan belongs to one worktree and from inside it the others are invisible. The
        plans of another workspace are still in the file, and `--all` is how you see them."""
        self.ok("plugin", "plans", "create", "here")
        doc = self._doc()
        doc["plans"][0]["workspace"] = "somewhere-else"
        self._file().write_text(json.dumps(doc))
        self.assertEqual(self.data("plugin", "plans", "list"), [])
        self.assertEqual([p["id"] for p in self.data("plugin", "plans", "list", "--all")],
                         ["p-1"])

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
        # rewrites a plan wholesale fails loudly instead of quietly losing the story.
        doc, seal = _plans()._read(self._dir())
        doc["plans"][0]["changelog"] = []
        with self.assertRaises(ValueError) as caught:
            _plans()._write(self._dir(), doc, seal)
        self.assertIn("append-only", str(caught.exception))
        self.assertEqual(len(self._doc()["plans"][0]["changelog"]), 1)

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
