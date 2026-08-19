"""The `plans` plugin — the state model, the verbs that move a step, and the catalogue.

Three classes, in the order the plugin was built: `PlansTest` is the state model below,
`StepsTest` is the lifecycle verbs, and `CatalogueTest` is the library, the templates and
the obligation — each with its own docstring saying what it is for.

The state model, pinning decisions rather than buying confidence. Everything sb owns — the
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
   alike, a file from a newer plugin, and any container a verb appends to that is not a
   list. The last of those is not tidiness: a `deps` holding a string makes `in` a
   substring test, and `s-1` reads as already present in `s-10`.
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
import re
import shutil
import subprocess
import sys
import time
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from switchboard import cli  # noqa: E402
from switchboard import plugins  # noqa: E402
from switchboard import store  # noqa: E402

from test_fork_lock import _held  # noqa: E402
from test_shipped_plugins import ShippedSandbox  # noqa: E402
from test_workspace import FakeHerdr  # noqa: E402


def _create(title: str, *steps: str) -> list[str]:
    """`create` in the required authoring syntax, from bare step names.

    A board name is required on the plan and on every step, and `--step` carries both as
    `<board name> = <what it is>` — one flag, so the two cannot desync. The labels here are
    derived rather than written (`shape the work` → `shape`), which keeps every test below
    reading as the sentence it cares about while still going through the real door.
    """
    argv = ["plugin", "plans", "create", title, "--display", f"board: {title}"]
    for s in steps:
        argv += ["--step", f"{s.split()[0] if s.split() else 'x'} = {s}"]
    return argv


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

    def catalogue(self, which: str) -> Path:
        """`library/` or `templates/`, in the copy of `defaults/` this sandbox runs from.

        The real shipped directories, copied by `Sandbox` along with the rest of
        `defaults/` — so a test that writes one here is writing what the plugin under test
        actually reads, and a test that deletes one is running the plugin with the empty
        catalogue the design says it must survive.
        """
        return self.defaults / "plugins" / "plans" / which

    def define(self, key: str, **spec) -> None:
        """One library definition. A `display` is filled in unless the test writes one.

        Because a display name is REQUIRED of a named step and `name-step` refuses a
        definition without one — so a definition written here with none would refuse every
        catalogue test for the one thing that test is not about. `display=None` is how a
        test asks for the definition that has no board label, and gets the refusal.
        """
        spec.setdefault("display", key)
        if spec.get("display") is None:
            spec.pop("display")
        d = self.catalogue("library")
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{key}.json").write_text(json.dumps(spec))

    def _dir(self) -> Path:
        return plugins.state_root("repo", self.repo) / "plans"

    def _file(self, plan: str = "p-1") -> Path:
        """One plan's own file, once the store has been moved to one file per plan."""
        return self._dir() / f"{plan}.json"

    def _files(self) -> list:
        """The plan files in id order, the way the plugin reads them — `p-10` after `p-2`
        and not between `p-1` and `p-2`, which is what sorting by name would give."""
        return sorted(self._dir().glob("p-*.json"), key=lambda f: int(f.stem[2:]))

    def _split(self) -> bool:
        """Is this sandbox's store one file per plan yet? The plugin asks the disk too."""
        return bool(self._files()) or (self._dir() / "_meta.json").exists()

    def migrate(self) -> str:
        """Move the sandbox's store to one file per plan, the only way anything does."""
        return self.ok("plugin", "plans", "migrate")

    def _stored(self) -> list:
        """Every file the store is actually kept in, whichever shape it is in."""
        d = self._dir()
        if not d.exists():
            return []
        return self._files() if self._split() else [f for f in [d / "plans.json"]
                                                    if f.exists()]

    def _raw(self) -> str:
        """The store's text, run together. For asserting what is NOT written down."""
        return "".join(f.read_text() for f in self._stored())

    def _doc(self) -> dict:
        """The store assembled the way `_read` assembles it, in whichever shape it is in.

        A helper and not the format: once a store is split there is no whole-store file, so
        a test that wants "the plans" builds the list the same way the plugin does.
        """
        if not self._split():
            f = self._dir() / "plans.json"
            return json.loads(f.read_text()) if f.exists() else {"plans": []}
        meta = self._dir() / "_meta.json"
        doc = json.loads(meta.read_text()) if meta.exists() else {}
        doc["plans"] = [json.loads(f.read_text()) for f in self._files()]
        return doc

    def edit_step(self, sid: str, **fields) -> None:
        """A hand-edit of one step's fields, which is how a lead shapes a plan now.

        The verbs that used to write `owner`, `gate`, `progress`, `why`, `tries` and
        `checkpoints` are gone — each was one field — so a test that used to type one edits
        the file instead, exactly as the guide tells a lead to. It writes no changelog
        entry, which is also true of a real editor and is why the plugin cannot police one.
        """
        doc = self._doc()
        step = next(s for pl in doc["plans"] for s in pl["steps"] if s["id"] == sid)
        step.update(fields)
        self._save(doc)

    def _save(self, doc: dict) -> None:
        """A hand-edit, written back the way a person would, into the shape on disk."""
        if not self._split():
            (self._dir() / "plans.json").write_text(json.dumps(doc))
            return
        for plan in doc["plans"]:
            (self._dir() / f"p-{int(str(plan['id']).lstrip('pP-'))}.json").write_text(
                json.dumps(plan))


class PlansTest(PlansSandbox):

    def test_a_plan_round_trips_empty_and_with_steps(self):
        """`create` with nothing makes a plan; `create` with steps makes the same plan with
        them already in it. The design says defining a plan upfront is the point, and that
        a lead may also start before the work is shaped — neither is the special case."""
        empty = self.data("plugin", "plans", "create", "--display", "board: untitled")
        self.assertEqual(empty["id"], "p-1")
        self.assertEqual(empty["steps"], [])

        made = self.data("plugin", "plans", "create", "build", "the", "plugin",
                         "--display", "board: build the plugin",
                         "--step", 'write = write it', "--step", 'test = test it',
                         "--note", "PR1 only", "--reason", "the job is shaped")
        self.assertEqual(made["id"], "p-2")
        self.assertEqual([s["id"] for s in made["steps"]], ["s-1", "s-2"])
        # An on-the-fly step owns its words: `name` filled and `def` null. The other way
        # round is a library step, and the whole schema is asserted here so that a field
        # added by a later PR has to be added deliberately rather than noticed later.
        self.assertEqual(made["steps"][0],
                         {"id": "s-1", "name": "write it", "display": "write", "def": None,
                          "obliged_by": None, "progress": "open", "why": None, "gate": None,
                          "owner": None, "tries": 1, "notes": [], "deps": [],
                          "checkpoints": []})
        # AUTO-CHAINED: the order the steps were typed in is an order, so `create` records
        # it rather than leaving a plan that warns about itself the moment it is made.
        self.assertEqual(made["steps"][1]["deps"], ["s-1"])
        self.assertEqual(made["display"], "board: build the plugin")
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
        self.ok("plugin", "plans", "create", "here", "--display", "board: here")
        doc = self._doc()
        doc["plans"][0]["checkout"] = "/somewhere/else"
        self._save(doc)
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
        made = self.data("plugin", "plans", "create", "a job",
                         "--display", "board: a job", "--step", 'write = write it')
        self.assertEqual(made["workspace"], "ws-1")
        self.assertEqual(made["workspace_from"], "agent")
        self.assertEqual(Path(made["checkout"]).resolve(), self.repo.resolve())

        self.ok("plugin", "plans", "create", "a second job",
                "--display", "board: a second job")
        subprocess.run(["git", "checkout", "-q", "-b", "fixups"], cwd=self.repo, check=True)

        self.assertEqual([p["id"] for p in self.data("plugin", "plans", "list")],
                         ["p-1", "p-2"])
        self.assertEqual(self.data("plugin", "plans", "show", "p-1")["workspace"], "ws-1")
        self.assertEqual(self.data("plugin", "plans", "create", "after the branch change",
                                   "--display", "board: after the branch change")
                         ["workspace"], "ws-1")

    def test_a_checkout_that_is_no_workspace_says_so(self):
        """No workspace row for this checkout, so there is no name to store. Written down
        as null and rendered as itself: a plausible-looking wrong key — the branch, the
        directory — would read to PR4 as a worktree that has gone."""
        made = self.data("plugin", "plans", "create", "in a plain clone",
                         "--display", "board: in a plain clone")
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
            made = self.data("plugin", "plans", "create", "during an outage",
                             "--display", "board: during an outage")
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
        self.ok("plugin", "plans", "create", "one",
                "--display", "board: one", "--step", 'a = a', "--step", 'b = b')
        self.ok("plugin", "plans", "create", "two",
                "--display", "board: two", "--step", 'c = c')
        self.assertEqual([s["id"] for s in self.data("plugin", "plans", "show", "p-2")
                          ["steps"]], ["s-3"])

        doc = self._doc()
        doc["plans"] = [p for p in doc["plans"] if p["id"] != "p-2"]
        self._save(doc)

        made = self.data("plugin", "plans", "create", "three",
                         "--display", "board: three", "--step", 'd = d')
        self.assertEqual(made["id"], "p-3")
        self.assertEqual([s["id"] for s in made["steps"]], ["s-4"])

    def test_the_changelog_is_append_only_and_carries_the_reason(self):
        """Written by the command, with the reason the agent supplied. A plan is reshaped
        as the job runs, and without this the file keeps only the final shape."""
        self.as_agent("w1")
        made = self.data("plugin", "plans", "create", "a job", "--display", "board: a job",
                         "--step", 'a = a', "--reason", "investigation landed")
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

    def test_an_unreadable_plan_costs_that_plan_and_nothing_else(self):
        """One plan is one file, and that is what a corrupt one costs: the plan in it.

        The whole reason for the layout. Before it, a malformed store refused every verb
        and blanked the board, so one bad file hid every good one. Now p-1 is skipped and
        SAID — a skipped file that nobody is told about is how a plan quietly stops
        existing — and the rest of the store answers normally.

        And nothing overwrites it: the file is byte-identical afterwards, and the next
        `create` mints p-3 rather than reusing the id of a plan it could not read.
        """
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.ok("plugin", "plans", "create", "another job",
                "--display", "board: another job")
        self.migrate()
        self._file("p-1").write_text("{ this is not json")

        out = self.ok("plugin", "plans", "list")
        self.assertIn("p-2", out)
        # Named, with the path and the promise, so a human knows which file to go and fix.
        self.assertIn("p-1 did not load", out)
        self.assertIn("not readable JSON", out)
        self.assertIn("will overwrite", out)
        self.assertEqual([p["id"] for p in self.data("plugin", "plans", "list")], ["p-2"])
        self.ok("plugin", "plans", "show", "p-2")

        code, _, err = self.sb("plugin", "plans", "show", "p-1")
        self.assertEqual(code, 1)
        self.assertIn("no plan p-1", err)
        # Never "the highest is p-2" while a p-1 sits on the disk unread — but the id is
        # still taken, so the counter must not hand it out again either.
        self.assertEqual(self.data("plugin", "plans", "create", "a third",
                                   "--display", "board: a third")["id"], "p-3")
        self.assertEqual(self._file("p-1").read_text(), "{ this is not json")

    def test_a_plan_file_malformed_inside_is_refused_by_name_and_alone(self):
        """`_check` is per file now, so each of these refuses one plan rather than the lot.

        Checked all the way down, not just at the top level — and the seal is why, not
        tidiness. It is keyed on the plan id, so a plan with none collapses into another's
        entry and `_write`'s drop check passes over the plan whose changelog is no longer
        in it. Refusing here is refusing before anything is written.

        What each wreck must do is two things at once: say what is wrong, naming the file,
        AND leave the good plan next to it readable. The second half is the whole change.
        """
        twins = [{"id": "s-1", "name": "one"}, {"id": "s-1", "name": "a twin"}]
        wrecks = {"holds a str where a plan should be": "hello",
                  "holds a NoneType where a plan should be": None,
                  "holds a plan with no usable id": {"title": "nameless"},
                  # The filename is the address, so a file whose plan says otherwise is a
                  # plan that two things disagree about where to find.
                  "a plan lives in the file its id names": {"id": "p-7"},
                  "whose steps are not a list": {"id": "p-9", "steps": "nope"},
                  "whose changelog is not a list": {"id": "p-9", "changelog": {}},
                  # A twin step takes a tick meant for the other and neither says so; a
                  # step with no id cannot be ticked at all.
                  "holds two steps called s-1": {"id": "p-9", "steps": twins},
                  "with no usable id": {"id": "p-9", "steps": [{"name": "nameless"}]},
                  # The containers the lifecycle verbs APPEND to. A null gives a raw
                  # AttributeError naming no file; a STRING is worse than a crash, because
                  # `in` degrades to a substring test and `dep s-2 --after s-1` would
                  # report the edge already present in a deps of "s-10" and drop it.
                  "whose deps are not a list": {"id": "p-9", "steps": [
                      {"id": "s-9", "deps": "s-10"}]},
                  "whose notes are not a list": {"id": "p-9", "steps": [
                      {"id": "s-9", "notes": None}]},
                  "whose checkpoints are not a list": {"id": "p-9", "steps": [
                      {"id": "s-9", "checkpoints": "notes/x.md"}]},
                  "has a p-9 whose notes is not a list": {"id": "p-9", "notes": None}}
        self.ok("plugin", "plans", "create", "the plan that is fine",
                "--display", "board: the plan that is fine")
        self.migrate()
        for expected, wreck in wrecks.items():
            with self.subTest(expected=expected):
                self._file("p-9").write_text(json.dumps(wreck))
                out = self.ok("plugin", "plans", "list")
                self.assertIn(expected, out)
                self.assertIn("p-9 did not load", out)
                # The good plan is still there, which is the point of the split.
                self.assertEqual([p["id"] for p in self.data("plugin", "plans", "list")],
                                 ["p-1"])
                self.assertEqual(json.loads(self._file("p-9").read_text()), wreck)
        self._file("p-9").unlink()

    def test_a_step_id_claimed_by_two_files_refuses_the_second(self):
        """Step ids are unique across the STORE and not within a file, because `tick s-7`
        names no plan. One file per plan cannot see that on its own, so `_read` checks it
        over the assembled set — and refuses the file that arrived second rather than both,
        so the plan that had the id first is untouched by somebody else's mistake."""
        self.ok("plugin", "plans", "create", "first",
                "--display", "board: first", "--step", 'do = do it')
        self.migrate()
        self._file("p-9").write_text(json.dumps(
            {"id": "p-9", "steps": [{"id": "s-1", "name": "a twin"}]}))
        out = self.ok("plugin", "plans", "list")
        self.assertIn("p-9 did not load", out)
        self.assertIn("p-1.json holds as well", out)
        self.assertEqual([p["id"] for p in self.data("plugin", "plans", "list")], ["p-1"])

    def test_a_store_from_a_newer_plugin_is_refused_whole(self):
        """The one thing a version marker can do, and the only moment it can do it. Whole
        and not per file, because the marker is the store's: a plugin that does not speak
        the format cannot know which of these files it would be misreading."""
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.migrate()
        (self._dir() / "_meta.json").write_text(json.dumps({"format": 99}))
        code, _, err = self.sb("plugin", "plans", "list")
        self.assertEqual(code, 1)
        self.assertIn("was written by a newer plans plugin", err)
        self.assertIn("will overwrite", err)

    def test_a_refusal_reaches_a_machine_reader_too(self):
        """sb prints `data` under `--json` and not `human`, so a reason that lives only in
        `human` is a reason for a person and for nobody else. PR4 and PR8 shell out for
        exactly these answers, and `ok:false` with a null payload gives them nothing to
        render or log."""
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        for argv, expected in ((("show", "p-9"), "the highest is p-1"),
                               (("changelog", "banana"), "is not a plan id")):
            with self.subTest(verb=argv[0]):
                code, out, _ = self.sb("plugin", "plans", *argv, "--json")
                self.assertEqual(code, 1)
                self.assertIn(expected, json.loads(out)["data"]["error"])

        # The cap covers `--reason` too — the one field every later verb carries into the
        # changelog, and the one an agent is most likely to write an essay into.
        code, out, _ = self.sb("plugin", "plans", "create", "a job",
                               "--display", "board: a job",
                               "--reason", "x" * 3000, "--json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["data"]["length"], 3000)

    def _at_write(self, *argv) -> list[tuple[bool, bool]]:
        """Which locks were held at the instant a plan file was replaced.

        Watched at `os.replace` rather than at the plugin's own `_write`: sb imports a
        plugin afresh on every invocation, so a patch on the module object is already stale
        by the time the command under test runs. Each fd is fresh, which conflicts with
        sb's own even inside this process.
        """
        held, real = [], os.replace

        def watched(src, dst):
            if re.fullmatch(r"p-\d+\.json|plans\.json", Path(dst).name):
                held.append((_held(self._dir() / ".lock"),
                             _held(self._dir() / ".mint.lock")))
            real(src, dst)

        with mock.patch("os.replace", watched):
            self.ok(*argv)
        return held

    def test_the_coarse_lock_is_gone_and_only_minting_takes_one(self):
        """The lock that used to wrap every command, including the reads, is not taken any
        more: one plan is one file and a write is tmp + `os.replace`, so a reader sees one
        version or the other and two commands on two plans were never in each other's way.

        What survives is the one race per-file storage does not answer — two commands
        reading the same counter and minting the same id — so the four verbs that ALLOCATE
        hold a lock across their mint and nothing else does. Asserted as a pair at the same
        instant, because "no lock at all" and "the wrong lock" are different bugs."""
        self.migrate()
        self.assertEqual(self._at_write("plugin", "plans", "create", "a job",
                                        "--display", "board: a job",
                                        "--step", "write = write it"),
                         [(False, True)])
        self.assertEqual(self._at_write("plugin", "plans", "tick", "s-1"),
                         [(False, False)])
        self.assertEqual(self._at_write("plugin", "plans", "note", "s-1", "--text", "x"),
                         [(False, False)])
        self.assertEqual(self._at_write("plugin", "plans", "add-step", "p-1", "and more",
                                        "--display", "more"),
                         [(False, True)])
        self.assertEqual([p["id"] for p in self.data("plugin", "plans", "list")], ["p-1"])

    def test_two_creates_racing_for_one_plan_file_cannot_both_have_it(self):
        """The id race, closed by the filesystem rather than by anybody's cooperation.

        `create` claims its `p-<n>.json` with `O_EXCL`, so a second process that got there
        first owns it and this one takes the next number instead of writing over a plan it
        never read. Provoked rather than hoped for: the interloper's file appears between
        this command's read and its claim, which is exactly the window a lock closes and
        the window this has to survive without one."""
        self.migrate()
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        real, raced = os.open, []

        def watched(path, flags, *a, **k):
            name = Path(str(path)).name
            if flags & os.O_EXCL and re.fullmatch(r"p-\d+\.json", name) and not raced:
                raced.append(name)
                # The other process, winning the file a hair before this one asks for it.
                Path(path).write_text(json.dumps(
                    {"id": "p-2", "title": "somebody else's", "display": "theirs",
                     "steps": [], "changelog": [], "notes": []}))
            return real(path, flags, *a, **k)

        with mock.patch("os.open", watched):
            made = self.data("plugin", "plans", "create", "another job",
                             "--display", "board: another job")
        self.assertEqual(raced, ["p-2.json"])
        self.assertEqual(made["id"], "p-3")
        self.assertEqual(json.loads(self._file("p-2").read_text())["title"],
                         "somebody else's")
        self.assertEqual([p["id"] for p in self.data("plugin", "plans", "list", "--all")],
                         ["p-1", "p-2", "p-3"])


class LegacyStoreTest(PlansSandbox):
    """The single-file store, which a new plugin must go on reading AND writing untouched.

    This is the coexistence half of the change, and the reason the first attempt at it was
    wrong. The store belongs to the repo, every worktree shares one, and the worktrees pick
    up a new plugin one at a time. So a plugin that moved the store to one file per plan the
    first time it read one would flip the shape under every worktree still on the old code,
    and each of them would refuse every plans command until somebody noticed. It did.

    What these pin is the fix: reading does not migrate, writing does not migrate, and the
    format on disk stays 1 — so an old plugin and this one are still looking at the same
    store afterwards.
    """

    def test_a_fresh_store_is_the_single_file_an_older_plugin_reads(self):
        """The default for a repo that has never had a plan. A new store in the new shape
        would be a new store an old plugin cannot read, which is the same break arriving by
        a different door."""
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.assertEqual(self._files(), [])
        self.assertFalse((self._dir() / "_meta.json").exists())
        self.assertEqual(json.loads((self._dir() / "plans.json").read_text())["format"], 1)

    def test_reading_a_legacy_store_never_moves_it(self):
        """Every read path, including the board's, which does not hold the lock. The verbs
        that only read are the ones that would have flipped a shared store silently."""
        self.ok("plugin", "plans", "create", "a job",
                "--display", "board: a job", "--step", 'do = do it')
        before = (self._dir() / "plans.json").read_bytes()
        for argv in (("list",), ("list", "--all"), ("show", "p-1"), ("changelog", "p-1"),
                     ("library",), ("guide",)):
            with self.subTest(verb=argv[0]):
                self.ok("plugin", "plans", *argv)
                self.assertEqual(self._files(), [], "a read moved the store")
        self.assertEqual((self._dir() / "plans.json").read_bytes(), before)

    def test_writing_a_legacy_store_keeps_it_legacy_and_keeps_format_1(self):
        """A tick is a whole-file rewrite in this shape — the cost of it, and the reason
        `migrate` exists. What must not change is the shape or the stamp: format 1 on disk
        is the only thing telling an old plugin it may still read this."""
        self.ok("plugin", "plans", "create", "a job",
                "--display", "board: a job", "--step", 'do = do it')
        self.ok("plugin", "plans", "tick", "s-1", "--reason", "done")
        self.ok("plugin", "plans", "note", "s-1", "--text", "and a note")
        self.assertEqual(self._files(), [])
        doc = json.loads((self._dir() / "plans.json").read_text())
        self.assertEqual(doc["format"], 1)
        self.assertEqual(doc["plans"][0]["steps"][0]["progress"], "done")
        # `broken` is the split store's answer to a file that did not load, and there is no
        # such thing here. Writing it down would put a field in a shared file that the
        # plugin on the next worktree has never heard of.
        self.assertNotIn("broken", doc)

    def test_a_legacy_store_still_refuses_whole_when_it_cannot_be_read(self):
        """One file means one blast radius, and that is honest rather than fixed here:
        starting over on a corrupt file would replace every plan in the repo on the next
        `create`. `migrate` is what makes a bad file cost one plan."""
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        (self._dir() / "plans.json").write_text("{ this is not json")
        code, _, err = self.sb("plugin", "plans", "list")
        self.assertEqual(code, 1)
        self.assertIn("not readable JSON", err)
        self.assertIn("will overwrite", err)
        self.assertEqual((self._dir() / "plans.json").read_text(), "{ this is not json")


class MigrationTest(PlansSandbox):
    """`migrate`: the one-time, hand-typed move from one `plans.json` to one file per plan.

    Three things have to survive it and one has to stop: every plan and its changelog come
    across untouched, the two counters come across, the old file is kept rather than
    deleted — and nothing but this verb ever performs it.

    Unproven here: two processes racing the verb. It runs under the state lock sb already
    holds for every plans command, and it is a thing a person types once, but nothing in
    this suite provokes the race.
    """

    LEGACY = {"format": 1, "next_plan": 12, "next_step": 61, "plans": [
        {"id": "p-2", "title": "an old plan", "workspace": "ws", "created_at": 1,
         "created_by": "lead", "steps": [{"id": "s-3", "name": "do it",
                                          "progress": "open"}],
         "notes": [], "changelog": [{"at": 1, "by": "lead", "action": "created",
                                     "reason": "because", "detail": None}]},
        {"id": "p-11", "title": "a newer one", "workspace": "ws", "created_at": 2,
         "created_by": "lead", "steps": [{"id": "s-60", "name": "and this",
                                          "progress": "done"}],
         "notes": [], "changelog": [{"at": 2, "by": "lead", "action": "created",
                                     "reason": None, "detail": "x"},
                                    {"at": 3, "by": "worker", "action": "ticked",
                                     "reason": "landed", "detail": "s-60"}]}]}

    def legacy(self, doc=None) -> Path:
        self._dir().mkdir(parents=True, exist_ok=True)
        f = self._dir() / "plans.json"
        f.write_text(json.dumps(doc if doc is not None else self.LEGACY, indent=2))
        return f

    def test_nothing_but_the_verb_moves_a_store(self):
        """The whole revision, in one assertion. Every verb runs against the old store and
        leaves it exactly as it was; then `migrate` moves it, and only then."""
        self.legacy()
        self.ok("plugin", "plans", "list", "--all")
        self.ok("plugin", "plans", "show", "p-2")
        self.ok("plugin", "plans", "tick", "s-3", "--reason", "done")
        self.ok("plugin", "plans", "create", "one more", "--display", "board: one more")
        self.assertEqual(self._files(), [])
        self.assertEqual(json.loads((self._dir() / "plans.json").read_text())["format"], 1)
        self.migrate()
        self.assertEqual([f.name for f in self._files()],
                         ["p-2.json", "p-11.json", "p-12.json"])

    def test_an_old_store_moves_across_whole_and_the_old_file_is_kept(self):
        self.legacy()
        out = self.migrate()
        self.assertEqual([p["id"] for p in self.data("plugin", "plans", "list", "--all")],
                         ["p-2", "p-11"])
        self.assertEqual([f.name for f in self._files()], ["p-2.json", "p-11.json"])
        # Every plan, and every changelog entry in it, exactly as it was. The records are
        # the reason any of this is careful, so they are compared whole and not counted.
        for was in self.LEGACY["plans"]:
            self.assertEqual(json.loads(self._file(was["id"]).read_text()), was)
        # Moved aside, never deleted: records are kept, and a migration is exactly the
        # moment somebody would want the file back.
        self.assertEqual(json.loads((self._dir() / "plans.json.migrated").read_text()),
                         self.LEGACY)
        self.assertIn("plans.json.migrated", out)

    def test_a_migration_that_died_half_way_still_reads_as_the_store_it_was(self):
        """THE CRASH THIS VERB IS ORDERED AROUND. Half-done has to read as not-done.

        `migrate` writes the per-plan files first. If it dies there — power, a kill, a full
        disk — the directory holds some plan files AND the complete format-1 `plans.json`
        every other worktree in the repo is still reading. Deciding "split" off the files
        alone made this plugin read a different store from every older one, each holding a
        different subset, with `migrate` refusing to re-run because it thought it was done.

        So the counters sidecar is what says split, and it is written LAST — after the
        legacy file has been moved aside. Every state before that reads as legacy, which is
        the state the fleet is actually in, and re-running the verb finishes the job.
        """
        self.legacy()
        d = self._dir()
        # Exactly what a crash after the first plan file leaves behind.
        (d / "p-2.json").write_text(json.dumps(self.LEGACY["plans"][0]))
        self.assertFalse((d / "_meta.json").exists())

        self.assertEqual([p["id"] for p in self.data("plugin", "plans", "list", "--all")],
                         ["p-2", "p-11"], "both plans, out of the file that still holds them")
        self.assertEqual(json.loads((d / "plans.json").read_text())["format"], 1,
                         "and an older plugin reads the same store it always did")

        self.migrate()
        self.assertEqual([f.name for f in self._files()], ["p-2.json", "p-11.json"])
        self.assertEqual([p["id"] for p in self.data("plugin", "plans", "list", "--all")],
                         ["p-2", "p-11"])
        self.assertEqual(json.loads((d / "plans.json.migrated").read_text()), self.LEGACY)

    def test_the_counters_sidecar_is_written_after_the_legacy_file_is_moved_aside(self):
        """The ordering itself, pinned rather than left to be re-derived from the crash
        test above: a store holding the plan files and the sidecar but still holding a
        format-1 `plans.json` is a state this verb must never leave behind."""
        self.legacy()
        self.migrate()
        d = self._dir()
        self.assertTrue((d / "_meta.json").exists())
        self.assertEqual(json.loads((d / "plans.json").read_text())["format"], 2,
                         "what is left at the old path is the tombstone, not a store")

    def test_the_verb_says_out_loud_what_it_costs_the_rest_of_the_fleet(self):
        """A one-way door on state the whole repo shares. The warning is the output and not
        a footnote in it, because the failure it is warning about is silent: an old plugin
        on another worktree just starts refusing, and nothing connects that to this."""
        self.legacy()
        out = self.migrate()
        self.assertIn("THIS FLIPS THE STORE FOR THE WHOLE REPO", out)
        self.assertIn("REFUSE every plans command", out)
        # And how to put it back, in the same breath — a warning with no way out of it is
        # a warning nobody can act on once they have read it too late.
        self.assertIn("plans.json.migrated", out)
        self.assertTrue(self.data("plugin", "plans", "migrate")["migrated"] is False)

    def test_migrating_twice_says_so_rather_than_doing_it_again(self):
        self.legacy()
        self.migrate()
        after = self._file("p-2").read_text()
        again = self.data("plugin", "plans", "migrate")
        self.assertEqual(again, {"migrated": False, "plans": []})
        self.assertEqual(self._file("p-2").read_text(), after)
        self.assertEqual([f.name for f in self._files()], ["p-2.json", "p-11.json"])

    def test_the_counters_come_across_and_are_not_recomputed_downwards(self):
        """`next_plan` is 12 with the highest plan at p-11, and `next_step` is 61 with the
        highest step at s-60 — ids are never reused, so a migration that recomputed them
        off what is present would be free to hand out one that a deleted plan once had."""
        self.legacy()
        self.migrate()
        self.assertEqual(self.data("plugin", "plans", "create", "a fresh one",
                                   "--display", "board: a fresh one")["id"],
                         "p-12")
        self.assertEqual(json.loads((self._dir() / "_meta.json").read_text())["format"], 2)
        made = self.data("plugin", "plans", "add-step", "p-12", "next", "--display", "next",
                         "--reason", "because")
        self.assertEqual(made["step"]["id"], "s-61")

    def test_an_old_file_restored_beside_a_moved_store_is_left_alone(self):
        """Somebody restores a `plans.json` from a backup next to a store that has already
        moved. Merging it would overwrite plans that have moved on since; the split store
        is the one that is live, and the verb says it has nothing to do."""
        self.legacy()
        self.migrate()
        self.ok("plugin", "plans", "tick", "s-3", "--reason", "done now")
        after = self._file("p-2").read_text()
        self.legacy()                   # the old file, back again
        self.ok("plugin", "plans", "list", "--all")
        self.assertFalse(self.data("plugin", "plans", "migrate")["migrated"])
        self.assertEqual(self._file("p-2").read_text(), after)
        self.assertEqual([f.name for f in self._files()], ["p-2.json", "p-11.json"])

    def test_a_store_that_moved_leaves_an_older_plugin_something_it_refuses(self):
        """After the deliberate flip — and only after it — an old plugin must refuse rather
        than misread. Without the tombstone it would find no `plans.json` in a store full of
        plans, read the repo as empty, and write a second store beside the real one."""
        self.legacy()
        self.migrate()
        tomb = json.loads((self._dir() / "plans.json").read_text())
        self.assertEqual(tomb["format"], 2)
        self.assertNotIn("plans", tomb)
        # And this plugin reads its own tombstone as what it is, not as a store to move.
        self.ok("plugin", "plans", "list", "--all")
        self.assertEqual([f.name for f in self._files()], ["p-2.json", "p-11.json"])

    def test_an_old_store_that_cannot_be_split_is_refused_rather_than_half_moved(self):
        """Two plans claiming one id would collapse into one filename and one of them would
        be gone. Half a store in each shape is the one outcome worth failing loudly for, so
        the migration refuses and the old file is left exactly where it is."""
        self.legacy({"format": 1, "plans": [{"id": "p-1"}, {"id": "1"}]})
        code, _, err = self.sb("plugin", "plans", "migrate")
        self.assertEqual(code, 1)
        self.assertIn("holds two plans called p-1", err)
        self.assertIn("will overwrite", err)
        self.assertEqual(self._files(), [])
        self.assertTrue((self._dir() / "plans.json").exists())

    def test_a_repo_with_no_plans_yet_still_moves_when_it_is_told_to(self):
        """Otherwise a repo that migrates before its first plan silently stays old, and the
        next `create` puts a single-file store back where the fleet just left."""
        self.assertTrue(self.data("plugin", "plans", "migrate")["migrated"])
        self.ok("plugin", "plans", "create", "the first plan",
                "--display", "board: the first plan")
        self.assertEqual([f.name for f in self._files()], ["p-1.json"])


class StepsTest(PlansSandbox):
    """What moves a step: `tick`, `note`, `dep`, `add-step` — and the file, for the rest.

    Most of what a lead does to a step is a FIELD — an owner, a gate, a skip and its
    reason, a checkpoint, a try count — and every one of those was a verb once. They are
    edited now, which is why half the tests here hand-edit the file and then assert the
    same thing the verb's test asserted: the rule outlives the verb or removing the verb
    removed the rule. The refusals those verbs carried are warnings now, in `validate` and
    on the board, and they are asserted in `HandEditTest`.

    Unproven here: that a lead actually ticks its steps, and that two `sb` processes moving
    two steps at once interleave correctly — the first is a workflow question and the second
    is `test_the_coarse_lock_is_gone_and_only_minting_takes_one` plus the mint lock, not a
    race this suite provokes.
    """

    def plan(self, *steps: str) -> dict:
        """One plan with its steps already in it, which is what every test here starts from.

        Through the required authoring syntax — a board name in front of every step name,
        and one for the plan — because that is what a compliant plan is now made with, and
        a helper that reached round the requirement would leave every test below running
        against a plan the plugin itself warns about.
        """
        return self.data(*_create("a job", *steps))

    def step(self, sid: str) -> dict:
        """One step, read back out of the file rather than out of a verb's own answer."""
        return next(s for p in self._doc()["plans"] for s in p["steps"] if s["id"] == sid)

    def actions(self, plan: str = "p-1") -> list[str]:
        return [e["action"] for e in self.data("plugin", "plans", "changelog", plan)]

    # -- an owner, and tick ----------------------------------------------------

    def test_an_owner_is_a_field_and_tick_is_the_verb_beside_it(self):
        """A lead writes the owner into the file, the owner works, somebody ticks. Only
        one of the two is a verb, and it is the frequent one: `tick` writes the step it
        names and leaves the changelog carrying the reason the agent supplied, which is the
        record the analysis pass reads and the only place the old shape of the plan
        survives. The owner beside it is a name in a field and nothing more."""
        self.plan("write it", "review it")
        self.as_agent("lead-1")
        self.edit_step("s-1", owner="w1")
        shown = self.ok("plugin", "plans", "tick", "s-1", "--reason", "the diff is in")

        self.assertEqual(self.step("s-1")["owner"], "w1")        # untouched by the tick
        self.assertEqual(self.step("s-1")["progress"], "done")
        self.assertEqual(self.step("s-2")["progress"], "open")   # only the step it named
        self.assertIn("s-1", shown)
        self.assertIn("done", shown)

        self.assertEqual(self.actions(), ["create", "tick"])
        entries = self.data("plugin", "plans", "changelog", "p-1")
        self.assertEqual(entries[1]["reason"], "the diff is in")
        self.assertEqual(entries[1]["by"], "lead-1")
        self.assertIn("open → done", entries[1]["detail"])

    def test_reassigning_overwrites_and_tells_nobody(self):
        """The design's rule, and the reason it is a rule: there is no core verb that can
        tell a running agent anything, so a notification here would be a promise this
        system cannot keep. Now that an owner is a field, the promise is even further away
        — nothing observes the write at all — and what is asserted is that no plans command
        reaches for `sb tell` on the way past."""
        self.plan("write it")
        self.edit_step("s-1", owner="w1")
        self.edit_step("s-1", owner="w2")

        # sb's own `git rev-parse` and `sb status` calls are its business; what must not
        # happen is an `sb tell` to the agent that lost the step.
        calls, real = [], subprocess.run
        with mock.patch("subprocess.run",
                        lambda argv, *a, **k: (calls.append(list(argv)),
                                               real(argv, *a, **k))[1]):
            self.ok("plugin", "plans", "show", "p-1")
            self.ok("plugin", "plans", "tick", "s-1")
        self.assertEqual([c for c in calls if "tell" in [str(w) for w in c]], [])

        self.assertEqual(self.step("s-1")["owner"], "w2")
        self.assertIn("(w2", self.ok("plugin", "plans", "show", "p-1"))

    # -- skip, which is a state in the file ------------------------------------

    def test_a_skip_keeps_its_reason_where_the_state_is(self):
        """On the step as well as in the changelog. A skipped step whose reason is twenty
        lines below in the changelog is an absence again by the time anybody scans the
        plan — the board is where a bad call has to be visible to be questioned. Written
        by hand now, which is why `why` being beside `progress` matters more and not
        less: the file is the only place the pair can be kept together."""
        self.plan("run the design gate")
        self.edit_step("s-1", progress="skipped", why="a one-line typo fix")
        self.assertEqual(self.step("s-1")["progress"], "skipped")

        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("skipped", shown)
        self.assertIn("a one-line typo fix", shown)
        # And nothing warns about it: a skip WITH its reason is a complete record.
        self.assertNotIn("incomplete", shown)
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

    def test_a_step_is_complete_or_skipped_and_never_both(self):
        """Structural, not checked: `progress` is one string, so whatever moves it second
        replaces what was there instead of joining it. What the changelog carries is which
        way the correction went — and the stale reason does not survive the correction, or
        a ticked step would still be carrying the sentence explaining why it was skipped."""
        self.plan("write it")
        self.edit_step("s-1", progress="skipped", why="not needed after all")
        self.ok("plugin", "plans", "tick", "s-1", "--reason", "it turned out to be needed")

        self.assertEqual(self.step("s-1")["progress"], "done")
        self.assertEqual(self.step("s-1")["why"], "it turned out to be needed")
        self.assertIn("skipped → done",
                      self.data("plugin", "plans", "changelog", "p-1")[1]["detail"])

    # -- note, checkpoint ------------------------------------------------------

    def test_notes_land_on_a_step_and_on_the_plan(self):
        """Both, because the design names both moments — the lead as it creates the plan,
        and whoever finishes a step as it is ticked. `p-1` is the plan; `s-1` and a bare
        `1` are the step, since every other verb here addresses a step by its number."""
        self.plan("write it")
        self.as_agent("w1")
        self.ok("plugin", "plans", "note", "s-1", "--text", "the parser was the hard part")
        self.ok("plugin", "plans", "note", "1", "--text", "and the tests were not")
        self.ok("plugin", "plans", "note", "p-1", "--text", "this job was mostly reading")

        self.assertEqual([n["text"] for n in self.step("s-1")["notes"]],
                         ["the parser was the hard part", "and the tests were not"])
        self.assertEqual(self.step("s-1")["notes"][0]["by"], "w1")
        self.assertEqual([n["text"] for n in self._doc()["plans"][0]["notes"]],
                         ["this job was mostly reading"])

        shown = self.ok("plugin", "plans", "show", "p-1")
        for text in ("the parser was the hard part", "this job was mostly reading"):
            self.assertIn(text, shown)
        self.assertEqual(self.actions(), ["create", "note", "note", "note"])

    def test_a_note_carries_a_reason_into_the_changelog_like_every_other_verb(self):
        """`note` is a mutating verb, so its changelog entry says why like the rest of them.
        Optional, because a note's text is usually its own reason and the callers that pass
        only `--text` predate the flag — what is pinned is that a reason, when given, lands
        on the entry for a step note and a plan note alike."""
        self.plan("write it")
        self.ok("plugin", "plans", "note", "s-1", "--text", "the parser was the hard part",
                "--reason", "so the next one knows where the time went")
        self.ok("plugin", "plans", "note", "p-1", "--text", "this job was mostly reading",
                "--reason", "the analysis pass reads this cold")
        self.ok("plugin", "plans", "note", "s-1", "--text", "and the tests were not")

        entries = self.data("plugin", "plans", "changelog", "p-1")
        self.assertEqual([e["reason"] for e in entries[1:]],
                         ["so the next one knows where the time went",
                          "the analysis pass reads this cold", None])
        self.assertIn("— so the next one knows where the time went",
                      self.ok("plugin", "plans", "changelog", "p-1"))
        # The note's own text is untouched by the reason: two fields, two jobs.
        self.assertEqual([n["text"] for n in self.step("s-1")["notes"]],
                         ["the parser was the hard part", "and the tests were not"])

    def test_a_checkpoint_is_a_reference_and_never_content(self):
        """A path, a URL or an id, and a paste is drawn red. The cost of the other way is
        not disk: a plan holding a copy of a brief is a second copy that goes stale, and a
        record read cold cannot tell which of the two the job actually used. The rule used
        to be a refusal inside a verb, which a hand-edit walked straight past; it is a
        warning now and it reaches the file, which is where the pastes actually arrive."""
        self.plan("write it")
        self.edit_step("s-1", checkpoints=[
            {"ref": ".switchboard/briefs/pr2-verbs/brief.md", "by": "w1", "at": 1}])
        self.assertIn("briefs/pr2-verbs/brief.md", self.ok("plugin", "plans", "show", "p-1"))
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

        self.edit_step("s-1", checkpoints=[
            {"ref": "# a brief\n\nwith its body in it", "by": "w1", "at": 1}])
        said = self.ok("plugin", "plans", "validate", "p-1")
        self.assertIn("s-1", said)
        self.assertIn("never content", said)
        self.assertIn("point the checkpoint at the file", said)
        # A warning and not a refusal: the plan still reads, and a tick on it still lands.
        self.ok("plugin", "plans", "show", "p-1")
        self.ok("plugin", "plans", "tick", "s-1")
        self.assertEqual(self.step("s-1")["progress"], "done")

    # -- rework, add-step, dep -------------------------------------------------

    def test_rework_is_a_count_on_the_step_and_never_an_edge(self):
        """A failed review sends its step back, and modelling that as a loop would make the
        plan cyclic to say something a counter says better. A count above one is what
        renders, so a first try shows no number at all and a second one does.

        Written by hand now — `tries` and `progress` are two fields — which changes nothing
        about the shape: what a re-entered step must NOT be is an edge back into the graph,
        and there is no verb and no field here that could make one."""
        self.plan("write it", "review it")
        self.ok("plugin", "plans", "tick", "s-1")
        self.assertNotIn("try ", self.ok("plugin", "plans", "show", "p-1"))

        self.edit_step("s-1", tries=2, progress="open", why="the review found a bug")
        self.assertIn("try 2", self.ok("plugin", "plans", "show", "p-1"))
        self.assertEqual(self.step("s-1")["deps"], [])          # a count, not a back-edge

        # Nothing downstream is un-ticked: the design makes that the lead's judgement, and
        # a rule here would either merge unreviewed work or throw away good review.
        self.edit_step("s-1", tries=3)
        self.assertEqual(self.step("s-2")["progress"], "open")
        self.assertEqual(self.actions(), ["create", "tick"])

    def test_add_step_mints_a_fresh_id_from_the_one_counter(self):
        """A step invented while the job runs is numbered from the same counter as every
        other step in the file, so "your step is s-3" names one thing across two plans. The
        reason matters more here than anywhere: rework leaves either a try count or an
        added step, and only the changelog can tell the analysis pass which happened."""
        self.plan("write it")
        self.ok("plugin", "plans", "create", "another job",
                "--display", "board: another job", "--step", 'elsewhere = elsewhere')
        made = self.data("plugin", "plans", "add-step", "p-1", "fix", "what", "review",
                         "found",
                             "--display", "fix", "--reason", "rework, as an added step")

        self.assertEqual(made["step"]["id"], "s-3")
        self.assertEqual(made["step"]["name"], "fix what review found")
        self.assertEqual(made["plan"], "p-1")
        self.assertEqual([s["id"] for s in self._doc()["plans"][0]["steps"]], ["s-1", "s-3"])
        self.assertEqual(self.data("plugin", "plans", "changelog", "p-1")[1]["reason"],
                         "rework, as an added step")

        code, out, _ = self.sb("plugin", "plans", "add-step", "p-9", "nowhere",
                               "--display", "nowhere", "--json")
        self.assertEqual(code, 1)
        self.assertIn("the highest is p-2", json.loads(out)["data"]["error"])

    def test_dep_records_an_edge_that_show_renders(self):
        """Fan-out and join, stored as data. Nothing traverses these, waits on them or
        orders anything by them — a join waits because the lead does not start it. So the
        whole of this verb is that the edge is stored, rendered, and points at a step that
        is really there."""
        self.plan("design", "build", "review", "merge")
        self.ok("plugin", "plans", "dep", "s-2", "--after", "s-1")
        self.ok("plugin", "plans", "dep", "s-4", "--after", "s-2", "--after", "3",
                "--reason", "the join")

        self.assertEqual(self.step("s-2")["deps"], ["s-1"])
        # `s-3` first because `create` chained it there when the plan was made, then the
        # two this verb added — an edge is appended, and the record keeps the order.
        self.assertEqual(self.step("s-4")["deps"], ["s-3", "s-2"])
        self.assertIn("after s-3, s-2", self.ok("plugin", "plans", "show", "p-1"))

        # Repeating an edge is not an error and does not double it; the plan is the same shape.
        self.ok("plugin", "plans", "dep", "s-2", "--after", "s-1")
        self.assertEqual(self.step("s-2")["deps"], ["s-1"])

        # And "already there" is decided on the NUMBER, like every other id comparison
        # here, so a bare `1` written by hand is the edge it names rather than a new one.
        doc = self._doc()
        doc["plans"][0]["steps"][2]["deps"] = ["1"]
        self._save(doc)
        self.ok("plugin", "plans", "dep", "s-3", "--after", "s-1")
        self.assertEqual(self.step("s-3")["deps"], ["1"])

    def test_an_edge_that_names_nothing_is_refused(self):
        """A cycle is not refused — nothing traverses an edge, so a cycle is a lead's
        mistake to read rather than a hang. An edge pointing at a step that does not exist,
        or lives in another plan, is a typo, and it renders as a wait that never ends."""
        self.plan("design", "build")
        self.ok("plugin", "plans", "create", "another job",
                "--display", "board: another job", "--step", 'elsewhere = elsewhere')
        for argv, expected in ((("dep", "s-2", "--after", "s-9"), "no step s-9"),
                               (("dep", "s-2", "--after", "s-2"), "cannot come after itself"),
                               (("dep", "s-2", "--after", "s-3"), "is not in p-1"),
                               (("dep", "s-2",), "--after is required")):
            with self.subTest(expected=expected):
                code, out, _ = self.sb("plugin", "plans", *argv, "--json")
                self.assertEqual(code, 1)
                self.assertIn(expected, json.loads(out)["data"]["error"])
                # What `create` chained, and nothing more: a refused edge writes nothing.
                self.assertEqual(self.step("s-2")["deps"], ["s-1"])

        # And a cycle, which is allowed, stays readable rather than hanging anything.
        self.ok("plugin", "plans", "dep", "s-2", "--after", "s-1")
        self.ok("plugin", "plans", "dep", "s-1", "--after", "s-2")
        self.assertIn("after s-2", self.ok("plugin", "plans", "show", "p-1"))

    # -- what every one of them owes -------------------------------------------

    def test_every_step_verb_logs_and_none_rewrites_the_plan(self):
        """The cross-cutting rule, checked once over every mutating verb rather than once
        each. `_write` refuses a document whose changelog is shorter than the one that was
        read, so a verb that rewrote a plan wholesale would fail here rather than quietly
        lose the story — running the whole set in sequence is what proves none of them does.
        """
        self.plan("write it", "review it")
        for argv in (("tick", "s-1"),
                     ("note", "s-1", "--text", "a note"), ("note", "p-1", "--text", "and one"),
                     ("add-step", "p-1", "a third", "--display", "third"),
                     ("dep", "s-3", "--after", "s-1"),
                     ("name-step", "p-1", "merge")):
            with self.subTest(verb=argv[0]):
                self.ok("plugin", "plans", *argv)
        self.assertEqual(self.actions(),
                         ["create", "tick", "note", "note", "add-step", "dep",
                          "name-step"])
        self.assertTrue(all(e["at"] for e in self.data("plugin", "plans", "changelog", "p-1")))

    def test_a_step_verb_on_a_step_that_is_not_there_is_refused_by_name(self):
        """Ids are never reused, so "there is no s-9 yet" and "s-9 was here and is gone" are
        different things and only the first can happen — which is what makes naming the
        highest a useful thing to say rather than a leak. Reaches a machine reader too."""
        self.plan("write it")
        for argv, expected in ((("tick", "s-9"), "the highest is s-1"),
                               (("note", "banana", "--text", "x"), "is not a step id"),
                               (("note", "s-9", "--text", "x"), "the highest is s-1")):
            with self.subTest(verb=argv[0]):
                code, out, _ = self.sb("plugin", "plans", *argv, "--json")
                self.assertEqual(code, 1)
                self.assertIn(expected, json.loads(out)["data"]["error"])
        self.assertEqual(self.actions(), ["create"])


class CatalogueTest(PlansSandbox):
    """The library, the templates and the obligation: links, copies, and what comes with what.

    Nine tests, and the axis every one of them is on is LIVE LINK versus COPY. A named step
    is a link, so editing a definition reaches a plan that is already running; a template is
    a copy, so editing the template reaches nothing. Those point opposite ways on purpose,
    and getting either backwards would look right in a screenshot and be wrong for the life
    of the design — which is why the tests here assert what is in the FILE and not only what
    `show` prints.

    The shipped catalogue is deliberately almost bare — `create-pr`, `merge`,
    `merge-human-review`, one template —
    so most of these write their own definitions into the sandbox's `defaults/`, which is
    also the honest way to test a catalogue whose contents PR9 is supposed to grow.

    Unproven here: that a lead reaches for the library at all rather than typing the step,
    which is a workflow question; and that the shipped catalogue is the right one, which the
    design says is read off real runs rather than decided now.
    """

    def steps(self, plan: str = "p-1") -> list[dict]:
        """The steps as STORED, not as rendered — the difference is the whole subject."""
        return next(p for p in self._doc()["plans"] if p["id"] == plan)["steps"]

    # -- a named step is a link ------------------------------------------------

    def test_a_named_step_links_to_its_definition_rather_than_copying_it(self):
        """The plan holds `def` and leaves `name` null, and the words come out of the
        library at render time. A copy would render identically today and stop tracking the
        definition tomorrow, which is exactly the failure nobody would notice."""
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        made = self.data("plugin", "plans", "name-step", "p-1", "merge-human-review",
                         "--reason", "this one is reviewed properly")

        (step,) = made["steps"]
        self.assertEqual(step["def"], "merge-human-review")
        self.assertEqual(step["id"], "s-1")
        self.assertIsNone(self.steps()[0]["name"])      # nothing copied into the record
        self.assertEqual(self.steps()[0]["def"], "merge-human-review")
        self.assertEqual(self.steps()[0]["progress"], "open")   # its own run object

        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("list what only a human can check", shown)
        self.assertIn("[merge-human-review]", shown)          # and it says that it IS a link

    def test_a_display_name_is_a_live_link_like_the_name_and_shows_in_the_library(self):
        """The short board label the library owns, resolved the same way the name is.

        A named step stores neither its name nor its display — both come out of the
        definition at render time, so editing the label reaches a plan already running. And
        `library` prints the label under the definition, so an author can see what the long
        name collapses to on the board without opening one.
        """
        self.define("scan", name="scan the whole codebase for the pattern", display="scan code")
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.ok("plugin", "plans", "name-step", "p-1", "scan", "--reason", "look first")

        # Stored as a link: neither the name nor the display is copied into the record.
        self.assertIsNone(self.steps()[0]["name"])
        self.assertIsNone(self.steps()[0].get("display"))
        # Resolved live in the read: `show --json` carries both, off the definition.
        shown = self.data("plugin", "plans", "show", "p-1")
        self.assertEqual(shown["steps"][0]["display"], "scan code")

        # Editing the label reaches the running plan, exactly as editing the name does.
        self.define("scan", name="scan the whole codebase for the pattern", display="grep it")
        self.assertEqual(
            self.data("plugin", "plans", "show", "p-1")["steps"][0]["display"], "grep it")

        # And the library verb shows the board label under the definition.
        lib = self.ok("plugin", "plans", "library", "scan")
        self.assertIn("grep it", lib)

    def test_a_key_too_long_for_its_column_still_keeps_a_gap_before_the_name(self):
        """`merge-human-reviewlist what only a human can check` was the render before this.

        The key column pads a short key and could not pad a long one, so an 18-character key
        ran straight into its name. Long keys now get a two-space floor, and short keys still
        start their name at the same column they always did — both catalogues render the same
        way, so a long template key cannot bring the defect back.
        """
        self.define("merge-human-review", name="list what only a human can check")
        self.define("scan", name="scan the whole codebase")
        lib = self.ok("plugin", "plans", "library")
        self.assertIn("merge-human-review  list what only a human can check", lib)
        self.assertIn("scan            scan the whole codebase", lib)

        d = self.catalogue("templates")
        d.mkdir(parents=True, exist_ok=True)
        (d / "a-very-long-template-key.json").write_text(
            json.dumps({"title": "a job", "steps": [{"name": "do it"}]}))
        self.assertIn("a-very-long-template-key  a job",
                      self.ok("plugin", "plans", "template", "list"))

    def test_editing_a_definition_reaches_a_plan_already_naming_it(self):
        """The point of the link, and the design's own words: editing a library step
        reaches every plan naming it, live ones included. The plan here is mid-flight — its
        step has an owner and has been reworked — and the new text still arrives, because
        there is no copy in the record for the edit to have missed."""
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.ok("plugin", "plans", "name-step", "p-1", "merge")
        self.edit_step("s-1", owner="w1", tries=2, progress="open")

        self.define("merge", name="land the branch, once Andrew says so",
                    obliges=["merge-human-review"])
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("land the branch, once Andrew says so", shown)
        self.assertNotIn("merge the pull request", shown)
        self.assertIsNone(self.steps()[0]["name"])      # still a link, not a refreshed copy

        # And the run state is the plan's, untouched by the definition changing under it.
        self.assertEqual(self.steps()[0]["owner"], "w1")
        self.assertEqual(self.steps()[0]["tries"], 2)

        # A definition that goes away says so rather than rendering a blank line.
        (self.catalogue("library") / "merge.json").unlink()
        self.assertIn("no such definition", self.ok("plugin", "plans", "show", "p-1"))

    def test_a_variant_is_an_on_the_fly_step_and_not_an_edited_link(self):
        """There is no verb that forks a definition for one job, and this is what stands in
        for one: `add-step`. The two live side by side in one plan — one owning its words,
        one owning a link — which is what "both are first class" means."""
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.ok("plugin", "plans", "name-step", "p-1", "merge-human-review")
        self.ok("plugin", "plans", "add-step", "p-1", "review it twice, it is a migration",
                "--display", "review",
                "--reason", "a variant, not a forked link")

        stored = self.steps()
        self.assertEqual([s["def"] for s in stored], ["merge-human-review", None])
        self.assertEqual(stored[1]["name"], "review it twice, it is a migration")
        # No verb takes a definition and rewrites it for one plan; the library is files.
        self.assertNotIn("edit", _plans_commands())

    # -- composition -----------------------------------------------------------

    def test_a_composite_expands_flat_with_fresh_ids(self):
        """A plan holds no containers: naming a composite puts its PARTS in, each a step in
        its own right with its own id, and nothing in the record says they arrived together.
        A step that contained another would be a plan by another name."""
        self.define("build", name="build it")
        self.define("ship", steps=["build", "merge"])
        self.ok("plugin", "plans", "create", "a job",
                "--display", "board: a job", "--step", 'shape = shape the work')
        made = self.data("plugin", "plans", "name-step", "p-1", "ship")

        # build, merge, and the review merge obliges — flat, in order, ids minted onwards
        # from the on-the-fly step that was already there.
        self.assertEqual([(s["id"], s["def"]) for s in made["steps"]],
                         [("s-2", "build"), ("s-3", "merge"), ("s-4", "merge-human-review")])
        self.assertEqual([s["def"] for s in self.steps()],
                         [None, "build", "merge", "merge-human-review"])
        self.assertTrue(all("steps" not in s for s in self.steps()))

    def test_a_circular_composite_is_refused(self):
        """Unlike a plan's `deps`, which nothing walks, composition IS traversed — so a
        cycle here is a hang rather than a lead's mistake to read. Refused before anything
        is written, naming the path, and the plan is untouched."""
        self.define("a", steps=["b"])
        self.define("b", steps=["a"])
        self.define("loop", steps=["loop"])
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        for name in ("a", "loop"):
            with self.subTest(name=name):
                code, out, _ = self.sb("plugin", "plans", "name-step", "p-1", name, "--json")
                self.assertEqual(code, 1)
                self.assertIn("composes into itself", json.loads(out)["data"]["error"])
        self.assertEqual(self.steps(), [])
        self.assertEqual([e["action"] for e in
                          self.data("plugin", "plans", "changelog", "p-1")], ["create"])

    # -- templates -------------------------------------------------------------

    def test_template_list_browses_and_use_copies_with_no_back_link(self):
        """A template is found rather than known up front, so it has to be browsable. Using
        one is copy and paste: the copy holds no reference to what it came from, and
        deleting the template afterwards changes nothing about the plan."""
        listed = self.ok("plugin", "plans", "template", "list")
        self.assertIn("docs", listed)
        self.assertIn("bring a document back in line with the code", listed)

        made = self.data("plugin", "plans", "template", "use", "docs",
                         "--title", "PR3 of the plans plugin",
                             "--reason", "the job is this job")
        self.assertEqual(made["title"], "PR3 of the plans plugin")
        self.assertEqual(made["notes"][0]["text"][:7], "Copied ")
        # Nothing anywhere in the record points back at the template it came from.
        self.assertNotIn("template", set(made) | {k for s in made["steps"] for k in s})

        shutil.rmtree(self.catalogue("templates"))
        self.assertIn("every claim the document makes",
                      self.ok("plugin", "plans", "show", "p-1"))
        self.assertIn("(no templates", self.ok("plugin", "plans", "template", "list"))

    def test_a_named_step_inside_a_template_stays_a_name(self):
        """The two mechanisms meet here and must not collapse into one: the plan is a COPY,
        and the merge step inside it is still a LINK. Flattening the names into copies at
        template time would be a plan that stops tracking its definitions the moment it is
        made, which is the same bug as snapshotting and harder to see."""
        self.data("plugin", "plans", "template", "use", "docs")
        stored = self.steps()
        self.assertEqual([s["def"] for s in stored],
                         [None, None, None, None, "merge", "merge-human-review"])

        self.define("merge", name="land it, once Andrew says so", obliges=["merge-human-review"])
        self.assertIn("land it, once Andrew says so", self.ok("plugin", "plans", "show", "p-1"))
        self.assertIsNone(self.steps()[4]["name"])

        code, out, _ = self.sb("plugin", "plans", "template", "use", "nope", "--json")
        self.assertEqual(code, 1)
        self.assertIn("no template 'nope'", json.loads(out)["data"]["error"])

    def test_a_templates_own_step_copies_its_display_name(self):
        """A template writes the long name, so it is where a short board label is authored —
        and unlike the name of a `def` entry, an own step's label is COPIED into the plan,
        because the step itself is a copy. So it is on the record and not resolved from
        anywhere: the shipped `docs` template's first step is `list every claim…`, drawn as
        `list claims`."""
        self.data("plugin", "plans", "template", "use", "docs")
        first = self.steps()[0]
        self.assertIn("every claim the document makes", first["name"])
        self.assertEqual(first["display"], "list claims")
        # The `def` entry carries no copied label; its display resolves live, like its name.
        self.assertIsNone(self.steps()[4]["display"])

    # -- the obligation --------------------------------------------------------

    def test_adding_a_merge_step_brings_its_review_by_every_route(self):
        """Obliged, not optional. Both routes that can put a library step in a plan go
        through one expansion, so there is no argument, no template shape and no ordering
        that lands a merge without its review — and the review says which merge it belongs
        to, which is what PR7's gate will read."""
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.data("plugin", "plans", "name-step", "p-1", "merge")
        self.assertEqual([(s["def"], s["obliged_by"]) for s in self.steps()],
                         [("merge", None), ("merge-human-review", "s-1")])

        # A second merge is a second thing to review: the dedupe is inside one act, not
        # across a plan, or the second merge would land with nothing reading its diff.
        self.data("plugin", "plans", "name-step", "p-1", "merge")
        self.assertEqual([(s["def"], s["obliged_by"]) for s in self.steps()],
                         [("merge", None), ("merge-human-review", "s-1"),
                          ("merge", None), ("merge-human-review", "s-3")])

        # And the other route in. `--reason` and nothing else: no flag turns this off.
        self.data("plugin", "plans", "template", "use", "docs")
        self.assertEqual([s["def"] for s in self.steps("p-2")][-2:],
                         ["merge", "merge-human-review"])
        self.assertEqual(sorted(_plans_args("name-step")), ["--reason", "name", "plan"])

    def test_an_obliged_step_is_skipped_with_a_reason_never_omitted(self):
        """The exchange the design makes: skipping is allowed and is expected to be rare,
        and what is paid for it is a state on the board with a sentence beside it. An
        omitted step is invisible; a skipped one can be seen and questioned."""
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.data("plugin", "plans", "name-step", "p-1", "merge")
        self.edit_step("s-2", progress="skipped", why="a one-line docs change")

        self.assertEqual(self.steps()[1]["progress"], "skipped")
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("skipped", shown)
        self.assertIn("a one-line docs change", shown)
        self.assertIn("obliged by s-1", shown)          # still on the board, not gone

        # And one without a reason is still called out, on an obliged step like on any
        # other — as a warning now rather than a refusal, since nothing can refuse a file.
        self.edit_step("s-2", why=None)
        self.assertIn("never an absence", self.ok("plugin", "plans", "validate", "p-1"))

    def test_a_definition_that_both_composes_and_obliges_is_refused(self):
        """An obligation attaches to a step, and a composite is not a step in a plan — only
        its parts ever appear — so there is no step for `obliged_by` to name. Dropping the
        obligation instead loses one in silence, which is the single thing this mechanism
        exists to prevent, and it would be invisible to whoever wrote the file."""
        self.define("signoff", name="get a signoff")
        self.define("landing", name="land it", steps=["merge"], obliges=["signoff"])
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")

        code, out, _ = self.sb("plugin", "plans", "name-step", "p-1", "landing", "--json")
        self.assertEqual(code, 1)
        self.assertIn("both composes", json.loads(out)["data"]["error"])
        self.assertEqual(self.steps(), [])

        # And it is refused when it is EXPANDED, not when the catalogue is loaded, so the
        # one bad definition takes down only what reaches it. A catalogue is edited by hand;
        # a typo in one file must not make every other definition unusable.
        self.ok("plugin", "plans", "name-step", "p-1", "merge")
        self.assertEqual([s["def"] for s in self.steps()], ["merge", "merge-human-review"])

        # An obligation that reaches back into its own chain is refused for the same reason
        # composition's cycle is: it is materialised, so it is walked.
        self.define("landing", name="land it", obliges=["signoff"])
        self.define("signoff", name="get a signoff", obliges=["landing"])
        code, out, _ = self.sb("plugin", "plans", "name-step", "p-1", "landing", "--json")
        self.assertEqual(code, 1)
        self.assertIn("obliges itself", json.loads(out)["data"]["error"])
        self.assertEqual([s["def"] for s in self.steps()], ["merge", "merge-human-review"])

    def test_every_obliging_step_gets_its_own_obliged_step(self):
        """No dedupe, anywhere: two merges are two diffs and therefore two reviews, whether
        they arrive in one act or two. Deduping would let one step's obligation be satisfied
        by a step it has nothing to do with — the door round the obligation in a tidier
        coat — and a lead who thinks one review covers both skips the second with that as
        the reason, which is visible where a dedupe would not have been."""
        self.define("land-both", name="land two branches", steps=["merge", "merge"])
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.data("plugin", "plans", "name-step", "p-1", "land-both")

        self.assertEqual([(s["def"], s["obliged_by"]) for s in self.steps()],
                         [("merge", None), ("merge", None),
                          ("merge-human-review", "s-1"), ("merge-human-review", "s-2")])

    # -- a broken catalogue ----------------------------------------------------

    def test_a_broken_catalogue_file_refuses_before_it_writes_anything(self):
        """The write-then-fail bug, pinned. A verb that wrote and THEN failed to render
        would report a failure over a mutation that had already landed, and the agent that
        retried it would get a second plan or a second changelog entry. So the catalogue is
        read on the way IN, and the state file is byte-identical after a refusal."""
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.data("plugin", "plans", "name-step", "p-1", "merge")
        before = self._raw()
        (self.catalogue("library") / "broken.json").write_text("{nope")

        # p-1 names a definition, so every verb that would render it has to resolve one.
        for argv in (("tick", "s-1"), ("tick", "s-2"),
                     ("add-step", "p-1", "and one more", "--display", "one more"),
                     ("note", "p-1", "--text", "a note"),
                     ("name-step", "p-1", "merge"), ("template", "use", "docs"),
                     ("show", "p-1"), ("list",), ("library",)):
            with self.subTest(verb=argv[0]):
                code, out, _ = self.sb("plugin", "plans", *argv, "--json")
                self.assertEqual(code, 1)
                # And the reason reaches a machine reader, which an escaped exception did
                # not — PR4 and PR8 shell out with --json and would get nothing at all.
                self.assertIn("not readable JSON", json.loads(out)["data"]["error"])
                self.assertEqual(self._raw(), before)

        # A broken TEMPLATE file is narrower again: it reaches the two verbs that read that
        # directory and nothing else.
        (self.catalogue("library") / "broken.json").unlink()
        (self.catalogue("templates") / "broken.json").write_text("[]")
        self.ok("plugin", "plans", "show", "p-1")
        for argv in (("template", "list"), ("template", "use", "docs")):
            with self.subTest(verb="template " + argv[1]):
                code, out, _ = self.sb("plugin", "plans", *argv, "--json")
                self.assertEqual(code, 1)
                self.assertIn("where a definition should be",
                              json.loads(out)["data"]["error"])
                self.assertEqual(self._raw(), before)

    def test_a_broken_catalogue_file_leaves_a_plan_that_named_nothing_alone(self):
        """Refusing the verbs that resolve a definition is right; refusing `show` on a plan
        that never named one is a typo in a shipped JSON file taking down every plan in the
        repo. The catalogue is not opened at all when there is no link to resolve."""
        self.ok("plugin", "plans", "create", "a job",
                "--display", "board: a job", "--step", 'just = just words')
        (self.catalogue("library") / "broken.json").write_text("{nope")

        for argv in (("show", "p-1"), ("list",), ("changelog", "p-1"),
                     ("tick", "s-1"), ("add-step", "p-1", "another", "--display", "anthr"),
                     ("create", "a second job", "--display", "board: a second job"),
                     ("template", "list")):
            with self.subTest(verb=argv[0]):
                self.ok("plugin", "plans", *argv)
        self.assertEqual(self.steps()[0]["progress"], "done")

    def test_a_definition_list_written_as_a_string_is_refused_by_name(self):
        """`"obliges": "merge-human-review"` iterates one letter at a time. It was refused before
        this — with `'x' obliges 'm', which is not in the step library`, which is a refusal
        that sends whoever has to fix the file looking in the wrong place."""
        self.define("x", name="a step", obliges="merge-human-review")
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        code, out, _ = self.sb("plugin", "plans", "name-step", "p-1", "x", "--json")
        self.assertEqual(code, 1)
        self.assertIn("read one letter at a time", json.loads(out)["data"]["error"])
        self.assertEqual(self.steps(), [])

    def test_a_definition_with_no_name_renders_as_its_own_key(self):
        """Not as "no such definition in the library", which is a lie about a file sitting
        right there and sends its reader looking for the wrong thing."""
        self.define("groundwork", about="a step somebody forgot to name")
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.ok("plugin", "plans", "name-step", "p-1", "groundwork")
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("groundwork", shown)
        self.assertNotIn("no such definition", shown)

    # -- an almost-empty catalogue ---------------------------------------------

    def test_the_system_works_with_the_catalogue_empty(self):
        """The design says so plainly, and it is a shipping constraint rather than an edge
        case: what belongs in the catalogue is read off real runs, so it starts nearly bare
        and everything except `name-step` has to carry on regardless."""
        shutil.rmtree(self.catalogue("library"))
        self.ok("plugin", "plans", "create", "a job",
                "--display", "board: a job", "--step", 'write = write it')
        self.ok("plugin", "plans", "add-step", "p-1", "and review it", "--display", "and")
        self.ok("plugin", "plans", "tick", "s-1")
        self.assertIn("empty", self.ok("plugin", "plans", "library"))
        self.assertIn("write it", self.ok("plugin", "plans", "show", "p-1"))

        code, out, _ = self.sb("plugin", "plans", "name-step", "p-1", "merge", "--json")
        self.assertEqual(code, 1)
        self.assertIn("the library is empty", json.loads(out)["data"]["error"])

        # A template naming a definition that is no longer there is refused too, rather
        # than copied in with a link that resolves to nothing.
        code, out, _ = self.sb("plugin", "plans", "template", "use", "docs", "--json")
        self.assertEqual(code, 1)
        self.assertIn("not in the step library", json.loads(out)["data"]["error"])


class CompletenessTest(PlansSandbox):
    """A display name and a dep on every step, and the three doors that keep them there.

    The board draws a plan as a left-to-right flowchart out of its deps and its labels, and
    before this was required not one plan in the live store set either — so the picture had
    never once been drawn. What is pinned here is the enforcement, which is deliberately not
    one rule in one place:

    1. The SHAPE VERBS refuse — `create`, `add-step`, `name-step`, `template use` will not
       mint a step with no display name, and the refusal shows what a good one looks like.
    2. EVERY OTHER WRITE warns and still writes. A `tick` that would not land because of a
       rendering rule is worse than the rendering, and this is the door a hand-edited file
       comes through — the plan file is meant to be edited by hand.
    3. `show` and `list` say so about a plan nobody has typed a verb at since.

    `_check` is NOT one of the doors, and the last test here is what says so: a plan
    missing both fields is still read, still listed and still ticked.
    """

    def setUp(self) -> None:
        super().setUp()
        self.workspace("ws", self.repo, agent="lead")
        self.as_agent("lead")

    def hand_edit(self, **step) -> None:
        """A plan written straight into the store, the way the guide says to edit one."""
        self.ok(*_create("a job", "write it"))
        doc = self._doc()
        doc["plans"][0].pop("display", None)
        doc["plans"][0]["steps"].append(
            {"id": "s-2", "name": "review it", "display": None, "def": None,
             "obliged_by": None, "progress": "open", "why": None, "gate": None,
             "owner": None, "tries": 1, "notes": [], "deps": [], "checkpoints": [],
             **step})
        self._save(doc)

    def test_the_shape_verbs_refuse_a_step_with_no_display_name(self):
        """The first door, and the refusal has to SHOW one rather than demand one.

        An agent told "display is required" types the full name in again — which is exactly
        how the field came to be empty everywhere — so every refusal here carries a worked
        example of the shortening it is asking for.
        """
        for argv in (("create", "a job", "--display", "board: a job", "--step", "write it"),
                     ("create", "a job")):
            with self.subTest(argv=argv):
                code, out, _ = self.sb("plugin", "plans", *argv, "--json")
                self.assertEqual(code, 1)
                why = json.loads(out)["data"]["error"]
                self.assertIn("display name", why)
                self.assertIn("list claims", why,
                              "the refusal shows what a good one looks like")
        self.assertEqual(self._doc()["plans"], [], "and nothing was written")

        self.ok(*_create("a job", "write it"))
        code, out, _ = self.sb("plugin", "plans", "add-step", "p-1", "review it", "--json")
        self.assertEqual(code, 1)
        self.assertIn("list claims", json.loads(out)["data"]["error"])
        self.assertEqual(len(self._doc()["plans"][0]["steps"]), 1)

    def test_a_definition_with_no_display_name_is_refused_at_name_step(self):
        """A named step draws its DEFINITION's label, so the refusal is about the file.

        There is no argument to this verb that could supply one: a display copied onto the
        step would be the live link quietly turned into a snapshot, which is the one thing
        naming a step is for.
        """
        self.define("groundwork", name="do the groundwork", display=None)
        self.ok(*_create("a job", "write it"))
        code, out, _ = self.sb("plugin", "plans", "name-step", "p-1", "groundwork", "--json")
        self.assertEqual(code, 1)
        self.assertIn("library/groundwork.json", json.loads(out)["data"]["error"])
        self.assertEqual(len(self._doc()["plans"][0]["steps"]), 1)

    def test_the_typed_order_is_an_order_and_create_chains_what_it_was_given(self):
        """`--step a --step b` is a lead saying what comes after what, so it is recorded.

        The alternative — every step a root — makes the one-shot `create` warn about itself
        the moment it is used, to be pedantic about an intent nobody doubts. A plan that is
        not a chain is reshaped with `dep`, which is the verb for it.
        """
        made = self.data(*_create("a job", "write it", "review it", "merge it"))
        self.assertEqual([s["deps"] for s in made["steps"]], [[], ["s-1"], ["s-2"]])
        self.assertEqual([s["display"] for s in made["steps"]],
                         ["write", "review", "merge"])
        self.assertNotIn("incomplete", made, "a plan made this way is complete")

    def test_a_hand_edited_plan_warns_on_a_tick_and_the_tick_still_lands(self):
        """The second door, and the whole of what it is for. Warns, never refuses.

        A `tick` that would not land because of a rendering rule is worse than the
        rendering: the record of what was done is the thing being protected, and a plan
        somebody edited in an editor is the ordinary way this file is written.
        """
        self.hand_edit()
        out = json.loads(self.ok("plugin", "plans", "tick", "s-2", "--json"))
        self.assertEqual(out["data"]["step"]["progress"], "done", "the tick landed")
        said = "\n".join(out["data"]["incomplete"])
        self.assertIn("s-2", said)
        self.assertIn("no display name", said)
        self.assertIn("no dep", said)
        self.assertIn("the plan has no display name", said)
        self.assertIn("dep s-2 --after", said, "and it says the command that fixes it")
        stored = self._doc()["plans"][0]["steps"][1]
        self.assertEqual(stored["progress"], "done", "and it is in the file, not only said")

    def test_show_and_list_draw_the_defect_on_a_plan_nobody_ran_a_verb_at(self):
        """The third door. A plan hand-edited and never touched again is still visibly
        wrong where a lead is looking — one character on the listing, the full account
        under `show`, and red on the board (`test_board.py`)."""
        self.hand_edit()
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("is incomplete", shown)
        self.assertIn("s-2", shown)
        self.assertTrue(self.ok("plugin", "plans", "list").startswith("!"),
                        "the listing marks it")

    def test_a_plan_missing_both_fields_is_still_read_listed_and_ticked(self):
        """`_check` is NOT a completeness door, and this is the test that says so.

        It refuses a FILE, and every plan written before this was required is missing both
        fields — so a completeness rule wired into it would take the board down to enforce
        a rendering preference. Structure is refused; completeness is always survivable.
        """
        self.hand_edit()
        for argv in (("show", "p-1"), ("list",), ("changelog", "p-1"), ("tick", "s-2"),
                     ("note", "s-2", "--text", "a note"), ("dep", "s-2", "--after", "s-1")):
            with self.subTest(verb=argv[0]):
                self.ok("plugin", "plans", *argv)

    def test_a_plan_draws_its_own_display_name_and_show_keeps_the_title(self):
        """Two views of one record: the board's header is the display and `show` is where
        the title is read. The plan's is LONGER than a step's — it owns the whole line —
        and it is a display version of the title rather than an abbreviation of it."""
        self.ok("plugin", "plans", "create", "fix the red CI on main, failing since Tuesday",
                "--display", "fix red CI: rich assertions on main",
                "--step", "list claims = list every claim the document makes")
        plan = self.data("plugin", "plans", "show", "p-1")
        self.assertEqual(plan["display"], "fix red CI: rich assertions on main")
        self.assertEqual(plan["title"], "fix the red CI on main, failing since Tuesday")
        self.assertIn("fix red CI: rich assertions on main",
                      self.ok("plugin", "plans", "list"), "the listing draws the display")

    def test_name_step_hangs_what_it_adds_off_the_plans_current_tail(self):
        """The flagship path: work, then `name-step merge`, and nothing complains.

        The obliged review used to land as a second root — no dep of its own — so the one
        command nearly every plan runs made that plan trip this file's own incompleteness
        door and draw red on the board from the moment it was typed. What lands now is the
        chain a lead would have written: the work, then the review, then the merge that
        waits on it.
        """
        self.define("merge", name="merge the pull request", obliges=["merge-human-review"])
        self.define("merge-human-review", name="list what only a human can check")
        self.data(*_create("a job", "write it", "review it"))
        added = self.data("plugin", "plans", "name-step", "p-1", "merge")

        self.assertNotIn("incomplete", added, f"no warning: {added}")
        self.assertNotIn("is incomplete", self.ok("plugin", "plans", "show", "p-1"))
        by_def = {s["def"]: s for s in added["steps"]}
        review, merge = by_def["merge-human-review"], by_def["merge"]
        self.assertEqual(review["deps"], ["s-2"], "the review comes after the work")
        self.assertEqual(merge["deps"], [review["id"]], "and the merge after the review")

    def test_a_library_step_named_into_an_empty_plan_is_the_root_it_really_is(self):
        """The other half of the same rule: there is nothing to hang off, so it is a root
        and that is not a defect. A warning here would be this file inventing an edge to a
        step that does not exist."""
        self.define("merge", name="merge the pull request", obliges=["merge-human-review"])
        self.define("merge-human-review", name="list what only a human can check")
        self.ok(*_create("a job"))
        added = self.data("plugin", "plans", "name-step", "p-1", "merge")
        self.assertNotIn("incomplete", added)
        by_def = {s["def"]: s for s in added["steps"]}
        self.assertEqual(by_def["merge-human-review"]["deps"], [])

    def test_a_template_entry_joining_two_earlier_ones_records_both_edges(self):
        """A join is `"after": [1, 2]`, and both halves of it have to land.

        Asking "has this step a dep yet" per edge made the second one a no-op — the first
        filled the field the second was testing — so a template that fanned out and joined
        back recorded a chain instead, silently, in the one file a lead cannot see the DAG
        of without drawing it.
        """
        d = self.catalogue("templates")
        d.mkdir(parents=True, exist_ok=True)
        (d / "fork.json").write_text(json.dumps(
            {"title": "fork and join", "display": "fork and join",
             "steps": [{"name": "scope it", "display": "scope"},
                       {"name": "build it", "display": "build", "after": [1]},
                       {"name": "document it", "display": "docs", "after": [1]},
                       {"name": "ship it", "display": "ship", "after": [2, 3]}]}))
        made = self.data("plugin", "plans", "template", "use", "fork")
        self.assertEqual([s["deps"] for s in made["steps"]],
                         [[], ["s-1"], ["s-1"], ["s-2", "s-3"]])
        self.assertNotIn("incomplete", made)

    def test_a_template_carries_its_own_display_names_and_the_order_between_its_steps(self):
        """The shipped `docs` template, used, which is the one plan a lead gets for free.

        What it has to land is a chain: every step with a board label, every step but the
        first with a dep, and its obliged human review before the merge it belongs to. A
        template that landed a loose stack would be the design's own example of the shape
        it says a plan must not have.
        """
        made = self.data("plugin", "plans", "template", "use", "docs")
        self.assertTrue(made["display"], "the copy has a board name of its own")
        self.assertEqual([s["deps"] for s in made["steps"]][0], [])
        self.assertTrue(all(s["deps"] for s in made["steps"][1:]),
                        f"every step but the first: {[s['deps'] for s in made['steps']]}")
        self.assertNotIn("incomplete", made)
        # The review is what the merge waits for, not the other way round: the list exists
        # to be read just before the gate.
        merge = next(s for s in made["steps"] if s.get("def") == "merge")
        review = next(s for s in made["steps"] if s.get("def") == "merge-human-review")
        self.assertIn(review["id"], merge["deps"])


class HandEditTest(PlansSandbox):
    """Editing the file IS the interface, so this is the class about the file.

    Five verbs went away in #4 — `assign`, `checkpoint`, `rework`, `gate`, `skip` — and each
    was one field with, at most, one refusal in front of it. What is pinned here is the half
    that could have been lost with them: three rules that lived ONLY inside a verb handler
    and are now checked against the file itself, where the hand-edits actually arrive, plus
    the two things that make editing the normal path rather than the fallback — a command
    that says which file to open, and a command that says what the edit broke.

    Never a refusal, anywhere in here. A plan that bricked the board because one step's
    gate read wrong would be a file nobody dares open, which is the opposite of the point.

    Unproven here: that the board redraw actually surfaces these within seconds of an edit.
    `test_board`'s red-draw tests prove the drawing; the interval is switchboard's.
    """

    def setUp(self) -> None:
        super().setUp()
        self.workspace("ws", self.repo, agent="lead")
        self.as_agent("lead")
        self.migrate()

    def plan(self, *steps: str) -> dict:
        return self.data(*_create("a job", *steps))

    # -- the three rules that used to live inside a verb ------------------------

    def test_the_guards_the_removed_verbs_kept_are_warnings_on_the_file_now(self):
        """`gate`, `skip` and `checkpoint` each refused one thing, and that refusal was the
        whole of what they bought over writing the field. Removing the verb would have
        removed the rule, so the rule moved to the door a hand-edit comes through — which
        is a WIDER door than the verbs ever were, since nothing checked a hand-edit before.

        All three at once and on one plan, because what is being pinned is that the set is
        checked rather than that one of them is."""
        self.plan("write it", "review it")
        self.ok("plugin", "plans", "tick", "s-1")
        self.edit_step("s-1", gate="he confirms the contract")
        self.edit_step("s-2", progress="skipped", why="   ",
                       checkpoints=[{"ref": "notes/a.md|s-9  done  merged", "by": "w",
                                     "at": 1}])

        said = self.data("plugin", "plans", "validate")
        self.assertFalse(said["ok"])
        lines = " ".join(said["plans"][0]["defects"])
        self.assertIn("already done", lines)            # a gate on a done step
        self.assertIn("never an absence", lines)        # skipped with no reason
        self.assertIn("never content", lines)           # a checkpoint that is not one line
        self.assertIn("s-1", lines)
        self.assertIn("s-2", lines)

        # Every one of them is a warning: the store still reads and still writes.
        self.assertEqual(self.sb("plugin", "plans", "validate")[0], 0)
        self.ok("plugin", "plans", "show", "p-1")
        self.ok("plugin", "plans", "tick", "s-2")
        self.assertEqual(self.step("s-2")["progress"], "done")

    def test_a_sound_hand_edit_says_nothing(self):
        """The other half, and the one that matters more: a file edited correctly must draw
        no red at all. A checker that flagged every plan would be a checker nobody reads."""
        self.plan("write it", "review it")
        self.edit_step("s-1", owner="w1", gate="he confirms the contract",
                       checkpoints=[{"ref": "notes/brief.md", "by": "lead", "at": 1}])
        self.edit_step("s-2", progress="skipped", why="a one-line docs change")
        said = self.data("plugin", "plans", "validate", "p-1")
        self.assertTrue(said["ok"])
        self.assertEqual(said["plans"][0]["defects"], [])
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

    def step(self, sid: str) -> dict:
        return next(s for pl in self._doc()["plans"] for s in pl["steps"] if s["id"] == sid)

    # -- validate ---------------------------------------------------------------

    def test_validate_checks_one_plan_or_all_of_them_and_never_refuses(self):
        """The verb a lead types on closing the editor. It runs the checks that already run
        — `_read`, `_defects`, the catalogue — at the one moment they are actually wanted,
        which is the whole difference between a rule enforced and a rule eventually noticed.

        `ok` stays true whatever it finds, and that is not a technicality: this is asked BY
        somebody who already suspects the file is wrong, so a non-zero exit would be the
        tool refusing to answer the question it was asked."""
        self.plan("write it")
        self.ok("plugin", "plans", "create", "another job", "--display", "board: another")
        doc = self._doc()
        doc["plans"][1]["display"] = ""
        self._save(doc)

        one = self.data("plugin", "plans", "validate", "p-1")
        self.assertEqual([f["id"] for f in one["plans"]], ["p-1"])
        self.assertTrue(one["ok"])

        every = self.data("plugin", "plans", "validate")
        self.assertEqual([f["id"] for f in every["plans"]], ["p-1", "p-2"])
        self.assertFalse(every["ok"])
        self.assertIn("no display name", " ".join(every["plans"][1]["defects"]))

        # Every plan says which file it is, so what it reports can be acted on.
        self.assertEqual(every["plans"][0]["file"], str(self._file("p-1")))

        # And a plan id that names nothing is said out loud rather than raised.
        code, out, _ = self.sb("plugin", "plans", "validate", "p-9")
        self.assertEqual(code, 0)
        self.assertIn("no plan p-9", out)

    def test_validate_reports_a_file_that_will_not_load_rather_than_raising(self):
        """The one thing `validate` is for above all: a file that has been edited into
        something the plugin cannot read. Every other verb refuses that file — correctly —
        so the verb that exists to ASK about it must not be the one that also refuses."""
        self.plan("write it")
        self._file("p-1").write_text("{ half an edit")
        code, out, _ = self.sb("plugin", "plans", "validate")
        self.assertEqual(code, 0)
        self.assertIn("not readable JSON", out)
        self.assertIn("nothing here will overwrite it", out)
        said = self.data("plugin", "plans", "validate")
        self.assertFalse(said["ok"])
        self.assertEqual([b["id"] for b in said["broken"]], ["p-1"])

    # -- the path a lead is told to open ----------------------------------------

    def test_create_and_template_use_print_the_file_to_edit(self):
        """The other end of "editing is the interface": the command that makes a plan says
        which file it made. Deriving it from the id and a convention read somewhere else is
        the kind of small friction that turns an editing workflow back into a verb one."""
        made = self.data(*_create("a job", "write it"))
        self.assertEqual(made["file"], str(self._file("p-1")))
        self.assertIn(str(self._file("p-2")), self.ok(*_create("another", "write it")))

        used = self.data("plugin", "plans", "template", "use", "docs",
                         "--display", "board: docs")
        self.assertEqual(used["file"], str(self._file(used["id"])))
        self.assertTrue(Path(used["file"]).exists())

    def test_an_unmigrated_store_is_pointed_at_the_file_it_really_has(self):
        """No `p-<n>.json` exists before `migrate`, so nothing invents one: what a legacy
        store gets told is the single file every plan of its actually lives in."""
        (self._dir() / "_meta.json").unlink()
        for f in self._files():
            f.unlink()
        (self._dir() / "plans.json").unlink()           # the tombstone `migrate` left
        made = self.data(*_create("a job", "write it"))
        self.assertEqual(made["file"], str(self._dir() / "plans.json"))
        self.assertTrue((self._dir() / "plans.json").exists())


class LivenessTest(PlansSandbox):
    """What `show` and `list` READ rather than hold: an owner's status, a plan's condition.

    The whole subject of this class is a negative — that none of it is ever written down —
    so every test here asserts the file as well as the rendering. The rest is the one
    asymmetry the derivation has to keep: an sb that does not answer produces `unknown`,
    never `dead` and never `abandoned`, because a plan is read cold by the analysis pass
    and a healthy job that read as abandoned for one instant leaves the same mark as one
    that fell apart.

    Driven against a real `sb` subprocess and a real store, the way the workspace tests
    above are — agent rows are written into the sandbox's own store and the plugin shells
    out to the sandbox's own build. There is no fake sb anywhere in here.

    Unproven, and not provable at this level: what an owner reads as while it is ALIVE
    depends on whether a herdr is answering on the machine the tests run on (`working` with
    none, `idle` with one that has never heard of a sandbox agent), so these assert the
    distinction — alive is not `dead`, and renders differently — rather than the word. And
    a worktree that is genuinely deleted under a running job is simulated by deleting the
    directory a plan's `checkout` names, which is the same fact the plugin reads but not
    the same act as `sb workspace close`.
    """

    def agent(self, name: str, *, workspace: str = "ws-1", state: str = "working") -> None:
        db = store.connect(self.repo)
        store.create_agent(db, name=name, role="worker", workspace=workspace,
                           cwd=str(self.repo))
        store.set_state(db, name, state)
        db.close()

    def moves(self, name: str, state: str) -> None:
        db = store.connect(self.repo)
        store.set_state(db, name, state)
        db.close()

    def test_an_owner_that_is_alive_and_one_that_is_dead_render_differently(self):
        """A step shows two things and only one of them is ticked: its progress, which a
        lead or the owner sets, and its owner's status, which is read off the agent. The
        lead learns of a death by reading the plan — switchboard's own failure notice goes
        to the dead agent's parent, which may be neither the lead nor anybody on the plan."""
        self.workspace("ws-1", self.repo, agent="lead-1")
        self.agent("w1")
        self.as_agent("lead-1")
        self.ok("plugin", "plans", "create", "a job",
                "--display", "board: a job", "--step", 'write = write it')
        self.edit_step("s-1", owner="w1")

        alive = self.data("plugin", "plans", "show", "p-1")["steps"][0]
        self.assertNotEqual(alive["owner_status"], "dead")
        self.assertIn(alive["owner_status"], ("working", "idle"))
        living = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn(f"(w1 — {alive['owner_status']})", living)

        self.moves("w1", "failed")
        dead = self.data("plugin", "plans", "show", "p-1")["steps"][0]
        self.assertEqual(dead["owner_status"], "dead")
        self.assertIn("(w1 — dead)", self.ok("plugin", "plans", "show", "p-1"))
        self.assertNotEqual(living, self.ok("plugin", "plans", "show", "p-1"))
        # And the step is untouched by all of it: progress is still what `create` wrote,
        # and nothing about the owner's death is anywhere in the file.
        self.assertEqual(dead["progress"], "open")
        step = self._doc()["plans"][0]["steps"][0]
        self.assertEqual(step["owner"], "w1")
        self.assertNotIn("owner_status", step)
        self.assertNotIn("dead", self._raw())

    def test_a_plan_goes_dormant_when_its_agents_close_and_comes_back_when_one_returns(self):
        """Every agent on the worktree closed is dormant, and dormant is a state a plan
        comes back from — nothing is deleted at any point, because cleanup means dropping
        out of a UI and never erasing a record."""
        self.workspace("ws-1", self.repo, agent="lead-1")
        self.agent("w1")
        self.as_agent("lead-1")
        self.ok("plugin", "plans", "create", "a job",
                "--display", "board: a job", "--step", 'write = write it')
        self.assertEqual(self.data("plugin", "plans", "show", "p-1")["condition"], "live")

        for name in ("lead-1", "w1"):
            self.moves(name, "done")
        self.assertEqual(self.data("plugin", "plans", "show", "p-1")["condition"], "dormant")
        self.assertIn("dormant", self.ok("plugin", "plans", "list"))

        self.moves("w1", "working")          # restored, and the plan is live again
        self.assertEqual(self.data("plugin", "plans", "show", "p-1")["condition"], "live")
        # None of the three readings left a mark: the record says what it always said.
        self.assertNotIn("condition", self._doc()["plans"][0])
        for word in ("dormant", "live"):
            self.assertNotIn(f'"{word}"', self._raw())

    def test_a_workspace_with_no_agents_at_all_is_not_dormant(self):
        """No agent is not the same fact as every agent closed, and `any()` over an empty
        list would call it one. Two ways in: a human makes a plan before anything is
        spawned into the worktree, and `sb status` is scoped to the caller's own tree so
        the agents on a worktree may belong to another. Neither is a dormancy."""
        self.workspace("ws-1", self.repo)               # a workspace, and nobody in it
        made = self.data("plugin", "plans", "create", "a job",
                         "--display", "board: a job", "--step", 'write = write it')
        self.assertEqual(made["workspace"], "ws-1")     # resolved, so `mine` is empty
        self.assertEqual(self.data("plugin", "plans", "show", "p-1")["condition"], "live")

        # And it still goes dormant once there IS somebody and they close.
        self.agent("w1")
        self.assertEqual(self.data("plugin", "plans", "show", "p-1")["condition"], "live")
        self.moves("w1", "done")
        self.assertEqual(self.data("plugin", "plans", "show", "p-1")["condition"], "dormant")

    def test_a_checkout_under_a_missing_ancestor_is_unknown_and_not_abandoned(self):
        """`os.stat` gives one ENOENT for a worktree that was deleted and for one whose
        parent went away under it — an unmounted volume, a moved `worktrees/` directory.
        The first is a job that fell apart and the second is a machine that moved, and
        `abandoned` is the verdict that never lifts once the analysis pass reads it."""
        root = Path(self.tmp.name) / "volume"
        (root / "spaces" / "co").mkdir(parents=True)
        self.ok("plugin", "plans", "create", "a job",
                "--display", "board: a job", "--step", 'write = write it')
        doc = self._doc()
        doc["plans"][0]["checkout"] = str(root / "spaces" / "co")
        self._save(doc)

        shutil.rmtree(root / "spaces" / "co")           # the worktree itself was deleted
        self.assertEqual(self.data("plugin", "plans", "show", "p-1")["condition"],
                         "abandoned")

        shutil.rmtree(root)                             # the ground moved instead
        shown = self.data("plugin", "plans", "show", "p-1")
        self.assertEqual(shown["worktree"], "unknown")
        self.assertEqual(shown["condition"], "unknown")
        self.assertNotIn("abandoned", self.ok("plugin", "plans", "show", "p-1"))

    def test_a_worktree_that_is_gone_is_abandoned_with_steps_open_and_finished_without(self):
        """The difference the sweep cannot make for itself. It deletes a worktree on gates
        that cannot see a plan, so if the record does not tell these apart afterwards the
        analysis pass reads every job that fell apart as a job that went well."""
        gone = Path(self.tmp.name) / "gone"
        gone.mkdir()
        self.ok("plugin", "plans", "create", "a job",
                "--display", "board: a job", "--step", 'write = write it')
        doc = self._doc()
        doc["plans"][0]["checkout"] = str(gone)
        self._save(doc)
        self.assertEqual(self.data("plugin", "plans", "show", "p-1")["condition"], "live")

        shutil.rmtree(gone)
        self.assertEqual(self.data("plugin", "plans", "show", "p-1")["condition"],
                         "abandoned")
        self.assertIn("worktree is gone", self.ok("plugin", "plans", "show", "p-1"))

        self.ok("plugin", "plans", "tick", "s-1")
        self.assertEqual(self.data("plugin", "plans", "show", "p-1")["condition"],
                         "finished")
        # Neither word is in the file, and the plan is still there to be read: a dormant or
        # dead plan is never deleted.
        self.assertNotIn("abandoned", self._raw())
        self.assertEqual(self._doc()["plans"][0]["id"], "p-1")

    def test_an_sb_that_cannot_be_reached_is_unknown_and_never_abandoned(self):
        """The bug this was written against. PR1 stores a null workspace for BOTH `none`
        and `unavailable`, so a derivation that read the null would let one timeout, at one
        instant, mark a healthy job abandoned for the rest of its life — nothing recomputes
        `workspace_from`, so the verdict would never lift. The worktree question is asked
        of the checkout PATH, which needs nobody's cooperation to answer."""
        (Path(self.tmp.name) / "bin").unlink()          # no build beside the plugin
        real = shutil.which
        with mock.patch("shutil.which",                 # and none on PATH either
                        lambda name, *a, **k: None if name == "sb" else real(name, *a, **k)):
            made = self.data("plugin", "plans", "create", "during an outage",
                             "--display", "board: during an outage",
                             "--step", 'write = write it')
            self.assertEqual(made["workspace_from"], "unavailable")
            self.edit_step("s-1", owner="w1")

            shown = self.data("plugin", "plans", "show", "p-1")
            # Unknown, and every other word is the bug: `abandoned` would be a lie the
            # record keeps, and `dormant` would be a claim about agents nothing looked at.
            # The worktree is still answered — that half needs no sb at all.
            self.assertEqual(shown["condition"], "unknown")
            self.assertEqual(shown["worktree"], "here")
            self.assertNotIn("abandoned", self.ok("plugin", "plans", "show", "p-1"))
            # And an owner nothing could be asked about is unknown, not dead. A lead that
            # read this as a death would dispatch a replacement for an agent that is fine.
            self.assertEqual(shown["steps"][0]["owner_status"], "unknown")
            self.assertNotIn("dead", self.ok("plugin", "plans", "show", "p-1"))

    def test_a_read_is_bounded_when_sb_hangs(self):
        """`show` runs with the plans lock held, so an sb that has wedged must cost seconds
        and a page of honest unknowns — never a hung `show`, and never every other plans
        command in the repo queued behind it."""
        self.ok("plugin", "plans", "create", "a job",
                "--display", "board: a job", "--step", 'write = write it')
        wedged = Path(self.tmp.name) / "bin"
        wedged.unlink()
        wedged.mkdir()
        (wedged / "sb").write_text("#!/bin/sh\nsleep 60\n")
        (wedged / "sb").chmod(0o755)

        started = time.monotonic()
        shown = self.data("plugin", "plans", "show", "p-1")
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual(shown["condition"], "unknown")
        self.assertIn("not the same as nobody working",
                      self.ok("plugin", "plans", "show", "p-1"))

    def test_a_crafted_name_cannot_forge_a_row(self):
        """A plan renders as rows and a row is a line, so a newline in a step name or an
        owner draws a step, or a status, that nobody wrote. Refused at the door — and
        escaped at the render as well, because a hand-edited plan file never came
        through a verb at all."""
        forged = "write it\ns-9     done      merged and shipped"
        code, out, _ = self.sb("plugin", "plans", "create", "a job",
                               "--display", "board: a job", "--step", forged,
                               "--json")
        self.assertEqual(code, 1)
        self.assertIn("one line", json.loads(out)["data"]["error"])
        for argv in (("create", "a job", "--step", "fine", "--reason", "why\nnot"),
                     ("create", "a job\nsecond line")):
            self.assertEqual(self.sb("plugin", "plans", *argv, "--json")[0], 1)

        self.ok("plugin", "plans", "create", "a job",
                "--display", "board: a job", "--step", 'write = write it')
        code, _, _ = self.sb("plugin", "plans", "note", "s-1",
                             "--text", "done\ns-9  done  merged", "--json")
        self.assertEqual(code, 1)

        # And the same name arriving the other way — somebody editing the file — renders
        # as the one line it was always entitled to, with the newline visible as itself.
        doc = self._doc()
        doc["plans"][0]["steps"][0]["name"] = forged
        doc["plans"][0]["steps"][0]["owner"] = "w1\nx"
        self._save(doc)
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("\\ns-9", shown)
        self.assertNotIn("\ns-9", shown)
        self.assertFalse([ln for ln in shown.splitlines() if ln.startswith("s-9")])

    def test_nothing_that_splits_a_line_survives_either_door(self):
        """The guarantee is a PROPERTY and not a list, so it is checked against the thing
        that defines it. A C0/C1 range misses U+2028 and U+2029, which `str.splitlines()`
        splits on — and a consumer that splits a rendering into rows is exactly what a
        board is, so a step name carrying one drew a row nobody added."""
        forged = "write it\u2028s-9     done      merged and shipped"
        self.assertEqual(self.sb("plugin", "plans", "create", "a job",
                                 "--display", "board: a job", "--step", forged,
                                 "--json")[0], 1)
        self.ok("plugin", "plans", "create", "a job",
                "--display", "board: a job", "--step", 'write = write it')

        breaks = [chr(c) for c in range(0x110000) if len(f"a{chr(c)}b".splitlines()) > 1]
        self.assertIn("\u2028", breaks)         # the sweep found what a range would miss
        plugin = _plans()                       # imported by the commands above
        for c in breaks:
            self.assertTrue(plugin._CONTROL.search(c), f"U+{ord(c):04X} is not refused")
            self.assertEqual(len(plugin._flat(f"a{c}b").splitlines()), 1,
                             f"U+{ord(c):04X} survives _flat")

        doc = self._doc()
        doc["plans"][0]["steps"][0]["name"] = forged
        self._save(doc)
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertFalse([ln for ln in shown.splitlines() if ln.startswith("s-9")])

    def test_a_refusal_cannot_forge_a_row_either(self):
        """An id is the one value a message here is built out of that nothing vetted — the
        refusal IS what happens when it fails to validate — so it is escaped where every
        other text is capped."""
        self.ok("plugin", "plans", "create", "a job",
                "--display", "board: a job", "--step", 'write = write it')
        for argv in (("show", "p-2\np-9   1 step   finished   forged"),
                     ("tick", "s-2\ns-9   done      merged"),
                     ("changelog", "p-2\np-9   forged")):
            code, out, _ = self.sb("plugin", "plans", *argv, "--json")
            self.assertEqual(code, 1)
            why = json.loads(out)["data"]["error"]
            self.assertEqual(len(why.splitlines()), 1)
            self.assertIn("\\n", why)


class TriggerTest(PlansSandbox):
    """The two halves of "an agent knows plans exist": the spawn trigger and the guide.

    The design splits them on cost. The trigger is one bullet paid on every spawn forever
    and says only the condition that makes an agent look; the instruction is the whole of
    how a plan is made and is read when a job comes up. So the properties worth pinning are
    that the trigger travels, that the instruction does NOT travel with it, and that
    deleting the plugin folder takes both away without stopping the fleet spawning — which
    is what the spec means by "delete = off = no agent is told plans exist".

    Spawning runs through `cli.main` against `test_workspace.FakeHerdr`, the same way
    `test_plugins`' injection tests do: what a fragment does at spawn is only observable in
    the prompt list herdr is handed, and asserting on `presets.resolve` instead would be
    asserting that a function this test does not exercise was called.

    Unproven here: that a model reads the trigger and acts on it. That is the workflow
    question the whole design rests on and no test can answer it.
    """

    def setUp(self) -> None:
        super().setUp()
        # The sandbox's own `enabled = ["plans"]` is what a repo adopting the plugin early
        # would write; these tests are about what SHIPS, so it goes and the shipped
        # `defaults/plugins.toml` answers instead.
        (self.sw / "plugins.toml").unlink()
        self.h = FakeHerdr(self.repo / "worktrees")

    def spawn(self, *argv) -> tuple[int, str, str]:
        with mock.patch.object(cli, "Herdr", lambda **kw: self.h):
            return self.sb("delegate", *argv)

    def prompts(self) -> list[str]:
        return self.h.started[-1]["prompts"]

    def test_the_guide_prints_the_plan_making_instruction(self):
        """The condition, the owner and the route to a template — the three things knowing
        plans exist does not tell you. Asserted on the rendered text rather than on the
        constant, because the constant is what a test would trivially agree with itself
        about and the printed block is what an agent reads."""
        out = self.ok("plugin", "plans", "guide")
        self.assertIn("heading for a change that will land", out)
        self.assertIn("sole worker", out)
        self.assertIn("counts as a lead", out)
        self.assertIn("sb plugin plans template list", out)
        self.assertEqual(json.loads(self.ok("plugin", "plans", "guide", "--json"))
                         ["data"]["guide"].strip(), out.strip())
        # Reads nothing and writes nothing: no state file exists after it runs.
        self.assertEqual(self._files(), [])

    def test_a_fresh_spawn_carries_the_trigger_and_not_the_guide(self):
        """Both halves of the split, in one assertion each. A spawn that carried the guide
        would be paying for the instruction on every agent forever, which is the thing the
        two-part shape exists to avoid."""
        code, _, err = self.spawn("do a thing")
        self.assertEqual(code, 0, err)
        prompts = self.prompts()
        self.assertIn(plugins.fragment(self.repo, "plans"), prompts)
        self.assertTrue(any("sb plugin plans guide" in p for p in prompts))
        for p in prompts:
            self.assertNotIn("WHEN A PLAN EXISTS", p)
            self.assertNotIn("\n", p)

    def test_deleting_the_plugin_folder_tells_nobody_and_stops_nothing(self):
        """"Off" for this design is "no agent is told", and the trigger lives in the folder
        precisely so that deleting it is that. The binding left behind in `presets.toml` is
        the shipped one, so this is also the asymmetry check: a binding that fails is
        skipped with a warning and the spawn goes ahead.

        The "no prompt names a plans command" sweep covers the role files too, and that is
        the point of asserting it on the whole prompt list rather than on the fragment
        alone: `lead.md` and `worker.md` say a plan is written down and who writes it, and
        they survive the plugin being deleted — so neither may name a verb that would then
        not dispatch. Naming one there is the same mistake as putting the trigger in
        `protocol.md`, and this is what catches it."""
        shutil.rmtree(self.defaults / "plugins" / "plans")
        code, _, err = self.spawn("do a thing")
        self.assertEqual(code, 0, err)
        self.assertIn("@plans", err)
        self.assertIn("skipped", err)
        for p in self.prompts():
            self.assertNotIn("sb plugin plans", p)
        code, _, err = self.sb("plugin", "plans", "guide")
        self.assertNotEqual(code, 0)


class GateTest(PlansSandbox):
    """The two gates: what the plugin represents, and everything it deliberately does not.

    A gate is a step's exit condition that requires a human, so almost everything worth
    pinning here is a negative — it is not a step of its own, `blocked` is not stored,
    nothing clears one, and nothing in this plugin merges, tears down or waits. It has no
    verb of its own any more: it is a field, written into the file like the rest of a
    plan's shape, and the one rule that used to be a verb's refusal — no gate on a step
    already done — is a warning the board draws red. The PROCEDURE at a gate is prose an
    agent follows, which is `guide` and `sb presets design-gate`, and the last two tests
    assert that the prose actually says the things a wrong reading of it would land a bad
    merge on.

    Unproven here, and not provable at this level: that an agent at a gate really blocks,
    that the merge chain runs on one approval and blocks on a conflict, and that a lead
    stays up while its child waits. All three are an agent following prose — there is no
    code path in this plugin to exercise for any of them, which is the design and is why
    the tests below are on the field and on the text rather than on a mechanism.
    """

    def agent(self, name: str, *, workspace: str = "ws-1", state: str = "working") -> None:
        db = store.connect(self.repo)
        store.create_agent(db, name=name, role="worker", workspace=workspace,
                           cwd=str(self.repo))
        store.set_state(db, name, state)
        db.close()

    def plan(self, *steps: str) -> dict:
        return self.data(*_create("ship a change", *steps))

    def step(self, sid: str) -> dict:
        return next(s for p in self._doc()["plans"] for s in p["steps"] if s["id"] == sid)

    def test_a_gate_is_an_exit_condition_on_a_step_and_never_a_step_of_its_own(self):
        """The design's first rule about gates, and the one thing here not to get wrong. A
        design step ending in "no implementation until he confirms" needs no second step for
        the confirmation, so marking one adds nothing to the plan: the same two steps, one
        of them now carrying the sentence saying what he has to answer."""
        self.plan("shape the work", "merge it")
        self.edit_step("s-1", gate="he confirms the behavioural contract")

        self.assertEqual([s["id"] for s in self._doc()["plans"][0]["steps"]], ["s-1", "s-2"])
        self.assertEqual(self.step("s-1")["gate"], "he confirms the behavioural contract")
        self.assertIsNone(self.step("s-2")["gate"])
        # Not a progress move: the step is still open, and what he answers is what ends it.
        self.assertEqual(self.step("s-1")["progress"], "open")

        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("he confirms the behavioural contract", shown)
        self.assertIn("no verb here does", shown)
        # And there is no verb for it: the field is the interface, so a `gate` command
        # arriving later would have to break this to get in.
        self.assertNotIn("gate", _plans_commands())
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

    def test_a_step_at_a_gate_renders_its_owner_blocked_and_stores_nothing(self):
        """What a gate looks like when it is reached: the owning agent blocks, and the step
        shows its owner blocked because that is read off the agent at the instant somebody
        draws the plan. PR4's derivation does the whole of it — this asserts that a gate
        needs no second mechanism and, more importantly, that `blocked` is nowhere in the
        file. A stored one would be a second record claiming to know, and it would still be
        claiming it after he had answered."""
        self.workspace("ws-1", self.repo, agent="lead-1")
        self.agent("w1")
        self.as_agent("lead-1")
        self.plan("shape the work")
        self.edit_step("s-1", gate="he confirms the contract", owner="w1")

        working = self.data("plugin", "plans", "show", "p-1")["steps"][0]
        self.assertNotEqual(working["owner_status"], "blocked")

        db = store.connect(self.repo)
        store.set_state(db, "w1", "blocked")
        db.close()
        at_gate = self.data("plugin", "plans", "show", "p-1")["steps"][0]
        self.assertEqual(at_gate["owner_status"], "blocked")
        self.assertIn("(w1 — blocked)", self.ok("plugin", "plans", "show", "p-1"))

        self.assertEqual(self.step("s-1")["progress"], "open")
        self.assertNotIn("owner_status", self.step("s-1"))
        self.assertNotIn("blocked", self._raw())

    def test_a_gate_is_skipped_with_a_reason_and_nothing_clears_one(self):
        """The only two ways past a gate, and the absence of a third. A trivially small
        change may skip it — with the reason, which a skip carrying none is warned about
        for — and the gate STAYS on the skipped step, because what makes a bad call
        questionable is that the board still says what was skipped as well as why.

        The rest is the absent verb, and it is absent twice over now: there is no `gate`
        command to take a `--clear`, and no other verb writes the field either. Emptying it
        by hand is the one bypass left, and the changelog entry an editor's author appends
        is what the design puts in its way — nothing here can, and nothing pretends to."""
        self.plan("shape the work")
        self.edit_step("s-1", gate="he confirms the contract")

        # A skip with no reason is not refused any more — nothing can refuse a file — but
        # it is drawn red and said out loud, which is the door that survives a hand-edit.
        self.edit_step("s-1", progress="skipped", why=None)
        said = self.ok("plugin", "plans", "validate", "p-1")
        self.assertIn("never an absence", said)
        self.assertIn("s-1", said)

        self.edit_step("s-1", why="a one-line typo fix")
        self.assertEqual(self.step("s-1")["progress"], "skipped")
        self.assertEqual(self.step("s-1")["gate"], "he confirms the contract")
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("a one-line typo fix", shown)
        self.assertIn("he confirms the contract", shown)
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

        # Read off the registry rather than off this file's memory of it: a verb that wrote
        # or cleared a gate would have to break this test to arrive.
        self.assertNotIn("gate", _plans_commands())
        self.assertNotIn("skip", _plans_commands())

    def test_a_gate_cannot_forge_a_row(self):
        """A gate is text that renders on a plan, so it goes through the door every field
        a hand-edit can reach goes through: escaped at the render. There is no door in
        front of it any more — the verb that used to refuse a newline is gone and a gate
        arrives by editing the file, which is the case this always had to cover anyway. A
        gate is the field an agent reads to decide whether a human is owed a block, so one
        that could draw a row nobody added is worse than most."""
        self.plan("shape the work")
        self.edit_step("s-1", gate="he approves\ns-9   done      merged")
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("\\ns-9", shown)
        self.assertNotIn("\ns-9   done", shown)
        self.assertFalse([ln for ln in shown.splitlines() if ln.startswith("s-9")])

    def test_a_gate_on_a_step_that_is_already_done_is_drawn_red(self):
        """A gate exists to be reached before the work it guards, so a plan authored after
        the fact does not get to mark one already passed. This was a refusal inside the
        `gate` verb and it is a warning now — which is the rule reaching FURTHER than it
        did, because the verb never saw the hand-edits that are how a gate arrives.

        Warned about with the two things that ARE allowed — reopen it if the gate is still
        ahead, record the skip and the reason that cleared it — and nothing is refused: the
        plan still reads, still ticks, and the board paints the step.

        A skipped step may carry one, which is the same rule from the other side: it is how
        a lead replacing a dead one records a gate the previous plan cleared."""
        self.plan("shape the work", "merge it")
        self.ok("plugin", "plans", "tick", "s-1", "--reason", "shaped")
        self.edit_step("s-1", gate="he confirms the contract")

        said = self.ok("plugin", "plans", "validate", "p-1")
        self.assertIn("s-1", said)
        self.assertIn("already done", said)
        self.assertIn("record the skip", said)
        # Reported and never refused: the plan reads and a verb on it still lands.
        self.assertIn("already done", self.ok("plugin", "plans", "show", "p-1"))
        self.assertEqual(self.data("plugin", "plans", "validate", "p-1")["ok"], False)
        self.ok("plugin", "plans", "note", "s-1", "--text", "still writable")

        # A skipped step carrying one is not a defect: that is the rule's other side.
        self.edit_step("s-2", progress="skipped", why="p-0 merged this already",
                       gate="he approves the merge")
        self.edit_step("s-1", gate=None)
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

    def test_the_design_gate_preset_is_nameable_and_bound_to_nothing(self):
        """D5, in the only two assertions that can tell the halves apart. Shipping the file
        makes it NAMEABLE — `sb presets design-gate` prints it, which is how a step names a
        format — and leaving it out of every binding is what makes it cost nothing: no
        spawn carries it, so a format read at one step by one agent is not paid for by the
        whole fleet. Spawn-only is convention rather than code, so there is nothing here
        that stops `--with design-gate`, and nothing asserting there is."""
        listed = json.loads(self.ok("presets", "--json"))
        self.assertIn("design-gate", listed["presets"])
        self.assertNotIn("design-gate", listed["all"])
        for role, bound in listed["roles"].items():
            self.assertNotIn("design-gate", bound, role)

        body = self.ok("presets", "design-gate")
        self.assertIn("twelve words", body)
        self.assertIn("fuller artifact", body)
        self.assertNotIn("BINDING", body)          # the editor's note is stripped, not read

        # The example has to BE the format, since being exact is this file's whole job: two
        # sections, and three indent levels each of which carries text. An example whose
        # `---` and `-----` were bare separator lines would contradict the sentence above
        # it, and an agent reading one and writing the other is the failure.
        marked = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("-")]
        for level in ("- ", "--- ", "----- "):
            self.assertTrue(any(ln.startswith(level) and ln[len(level):].strip()
                                for ln in marked), level)
        self.assertEqual([ln for ln in marked if ln in ("-", "---", "-----")], [])
        self.assertIn("What is causing it", body)
        self.assertIn("What the fix will be", body)

    def test_the_guide_points_at_the_catalogue_and_says_nothing_about_gates(self):
        """The guide is a pointer, and a gate is not one of the things it points at.

        A gate is a property of the step whose exit condition it is, so an agent meets one
        by reaching that step — where the definition's own `about` and `show`'s rendering
        of the field both say what it needs. Naming the gates in the guide as well put a
        second account, staler than those and read earlier, in front of every agent that
        had not reached one. So what is asserted is the route into the catalogue, the file
        and its rules, and the absence of a gate section.

        Asserted on the printed block rather than on the constant, like the guide test
        above — the constant is what a test would trivially agree with itself about."""
        out = self.ok("plugin", "plans", "guide")
        # Wrapping is layout and these are claims, so the claims are matched against the
        # text as one run: an assertion that also pinned where the line breaks fall would
        # fail the next time somebody reflows a paragraph and say nothing about the claims.
        said = " ".join(out.split())
        for expected in (
                # The catalogue, which is the only account of any particular step.
                "sb plugin plans library",
                "sb plugin plans template list",
                # The file, since past `create` the plan is edited rather than commanded.
                "agentflow/plugins/plans/",
                "One plan is one `p-<id>.json`",
                "sb plugin plans migrate",
                # The three things hand-editing can silently lose.
                "APPEND a changelog entry",
                "NEVER drop or rewrite an entry",
                "ADD A LIBRARY STEP with `name-step`, not by hand",
                # Who writes what. Shape is the lead's; a tick is whoever did the step.
                "The owner makes every edit to the SHAPE of the plan",
                "TICKING IS NOT THAT",
                "TICK A STEP BEFORE ITS TEARDOWN RUNS, never after"):
            self.assertIn(expected, said)
        # And no account of a gate. `gate` itself still appears, in the list of fields a
        # lead edits, which is the point: the guide knows the field exists and says nothing
        # about what any particular one needs. What must not come back is a section, so the
        # headings and the pointer that only a gate section would carry are what is pinned.
        for gone in ("THE TWO GATES", "THE DESIGN GATE", "THE MERGE GATE",
                     "sb presets design-gate"):
            self.assertNotIn(gone, said)
        # Still reads nothing and writes nothing.
        self.assertEqual(self._files(), [])


class MarkdownTest(PlansSandbox):
    """`show --markdown` — the rendering that goes on a pull request.

    Two decisions, and both are about what the comment on a PR must survive:

    1. It is ONE plan. The comment is posted by a step definition on a repo whose store
       holds every plan in the fleet, and the failure it is written against is a whole-store
       dump landing on somebody's PR.
    2. It is WALKED, not templated. The plan schema has moved twice already; a rendering
       with the fields written into it either raises or quietly drops one the week it moves
       again — from a step whose only job is to report, in front of a merge. So a field
       nothing here has ever seen appears on its own, and a field that goes away vanishes.

    Not pinned, deliberately: the layout. Asserting the exact table shape would be the
    per-field template these tests exist to say the renderer does not have.
    """

    def _plan(self) -> None:
        """A plan with something in every kind of field, on a second plan's store."""
        self.ok("plugin", "plans", "create", "the other job",
                "--display", "board: the other job", "--step", "othr = a step nobody wants")
        self.ok(*_create("render the plan", "write the renderer", "merge it"))
        self.ok("plugin", "plans", "note", "s-2", "--text", "waits on review")
        self.ok("plugin", "plans", "tick", "s-2", "--reason", "the diff is in")

    def test_markdown_renders_one_plan_and_never_the_store(self):
        """The plan asked for, in markdown, with no trace of the plan beside it."""
        self._plan()
        md = self.ok("plugin", "plans", "show", "p-2", "--markdown")
        self.assertTrue(md.lstrip().startswith("#"), md)
        for expected in ("p-2", "render the plan", "s-2", "write the renderer",
                         "waits on review", "the diff is in"):
            self.assertIn(expected, md)
        # The other plan is in the same store and none of it is here.
        for gone in ("p-1", "the other job", "a step nobody wants"):
            self.assertNotIn(gone, md)
        # And `--json` is what it always was: the plan record, untouched by the flag.
        self.assertEqual(self.data("plugin", "plans", "show", "p-2", "--markdown")["id"],
                         self.data("plugin", "plans", "show", "p-2")["id"])
        self.assertEqual(self.data("plugin", "plans", "show", "p-2", "--markdown"),
                         self.data("plugin", "plans", "show", "p-2"))

    def test_a_field_nobody_wrote_this_renderer_for_still_renders(self):
        """Schema drift, forwards: a plan carrying fields this code has never heard of —
        a scalar, a list of records, a nested map — renders them rather than dropping them
        or raising. This is what a plan written by a LATER plugin looks like to this one."""
        self._plan()
        doc = self._doc()
        plan = [p for p in doc["plans"] if p["id"] == "p-2"][0]
        plan["risk"] = "high"
        plan["reviews"] = [{"who": "andrew", "verdict": "ship it"}]
        plan["budget"] = {"agents": 3, "tokens": 900}
        plan["steps"][0]["mood"] = "cheerful"
        self._save(doc)

        md = self.ok("plugin", "plans", "show", "p-2", "--markdown")
        for expected in ("risk", "high", "reviews", "andrew", "ship it",
                         "budget", "agents", "900", "mood", "cheerful"):
            self.assertIn(expected, md)

    def test_a_plan_missing_the_fields_this_one_has_renders_too(self):
        """Schema drift, backwards: every optional field gone — no display, no notes, no
        changelog, a step that is an id and a name and nothing else. A plan hand-written by
        somebody, or made by an older plugin, still renders and still says which plan it
        is."""
        self._plan()
        doc = self._doc()
        doc["plans"] = [{"id": "p-2", "title": "a bare plan", "checkout": str(self.repo),
                         "steps": [{"id": "s-9", "name": "do the thing"}]}
                        if p["id"] == "p-2" else p for p in doc["plans"]]
        self._save(doc)

        md = self.ok("plugin", "plans", "show", "p-2", "--markdown")
        self.assertIn("p-2", md)
        self.assertIn("a bare plan", md)
        self.assertIn("do the thing", md)
        # And the empty plan, which is the far end of the same axis: a record with an id
        # and nothing else is a heading, not a traceback.
        self.assertIn("p-3", _plans()._markdown({"id": "p-3"}))

    def test_a_forged_row_cannot_forge_one_here_either(self):
        """A newline stored in a field is escaped, like everywhere else in this plugin —
        a markdown table is exactly what a stored `\\n` would be aiming at, and the pipe
        that would split a cell is escaped for the same reason."""
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        md = _plans()._markdown(
            {"id": "p-1", "title": "t",
             "changelog": [{"by": "a\nb", "action": "c|d", "reason": "e"}]})
        self.assertIn("a\\nb", md)
        self.assertNotIn("a\nb", md)
        self.assertIn("c\\|d", md)

    def test_the_flag_is_declared_on_show_and_nowhere_else(self):
        """One command renders a plan for a PR, and it is the one that reads a single plan
        by id — so there is no verb that could render the whole store as markdown."""
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        self.assertIn("--markdown", _plans_args("show"))
        for command in _plans_commands():
            if command != "show":
                self.assertNotIn("--markdown", _plans_args(command))


def _plans_commands() -> list[str]:
    """The verbs the plugin declares, read off the registry rather than off a docstring."""
    reg = plugins.Registry()
    _plans().register(reg)
    return list(reg.commands)


def _plans_args(command: str) -> list[str]:
    reg = plugins.Registry()
    _plans().register(reg)
    return [a.name for a in reg.commands[command].args]


def _plans():
    """The loaded plugin module, by the name sb imported it under."""
    return sys.modules[plugins._MODULE_PREFIX + "plans"]


if __name__ == "__main__":
    unittest.main()
