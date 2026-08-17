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

    def catalogue(self, which: str) -> Path:
        """`library/` or `templates/`, in the copy of `defaults/` this sandbox runs from.

        The real shipped directories, copied by `Sandbox` along with the rest of
        `defaults/` — so a test that writes one here is writing what the plugin under test
        actually reads, and a test that deletes one is running the plugin with the empty
        catalogue the design says it must survive.
        """
        return self.defaults / "plugins" / "plans" / which

    def define(self, key: str, **spec) -> None:
        d = self.catalogue("library")
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{key}.json").write_text(json.dumps(spec))

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
        # An on-the-fly step owns its words: `name` filled and `def` null. The other way
        # round is a library step, and the whole schema is asserted here so that a field
        # added by a later PR has to be added deliberately rather than noticed later.
        self.assertEqual(made["steps"][0],
                         {"id": "s-1", "name": "write it", "def": None, "obliged_by": None,
                          "progress": "open", "why": None, "owner": None, "tries": 1,
                          "notes": [], "deps": [], "checkpoints": []})
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
                  # The containers the lifecycle verbs APPEND to. A null gives a raw
                  # AttributeError naming no file; a STRING is worse than a crash, because
                  # `in` degrades to a substring test and `dep s-2 --after s-1` would
                  # report the edge already present in a deps of "s-10" and drop it.
                  "whose deps are not a list": {"plans": [{"id": "p-1", "steps": [
                      {"id": "s-1", "deps": "s-10"}]}]},
                  "whose notes are not a list": {"plans": [{"id": "p-1", "steps": [
                      {"id": "s-1", "notes": None}]}]},
                  "whose checkpoints are not a list": {"plans": [{"id": "p-1", "steps": [
                      {"id": "s-1", "checkpoints": "notes/x.md"}]}]},
                  "has a p-1 whose notes is not a list": {"plans": [{"id": "p-1",
                                                                    "notes": None}]},
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


class StepsTest(PlansSandbox):
    """The verbs that move a step: assign, tick, skip, note, checkpoint, rework, add-step, dep.

    Thirteen tests, and what each pins is a decision that could have gone the other way,
    not that a dict got a key. The ones that matter most are the refusals: a skip without a reason and
    a checkpoint carrying content are both things the design forbids in prose, and prose is
    not what an agent at 3am reads.

    Unproven here: that a lead actually ticks its steps, and that two `sb` processes moving
    two steps at once interleave correctly — the first is a workflow question and the second
    is `test_the_state_lock_is_held_while_a_command_writes` plus the lock, not a race this
    suite provokes.
    """

    def plan(self, *steps: str) -> dict:
        """One plan with its steps already in it, which is what every test here starts from."""
        argv = ["plugin", "plans", "create", "a job"]
        for s in steps:
            argv += ["--step", s]
        return self.data(*argv)

    def step(self, sid: str) -> dict:
        """One step, read back out of the file rather than out of a verb's own answer."""
        return next(s for p in self._doc()["plans"] for s in p["steps"] if s["id"] == sid)

    def actions(self, plan: str = "p-1") -> list[str]:
        return [e["action"] for e in self.data("plugin", "plans", "changelog", plan)]

    # -- assign and tick -------------------------------------------------------

    def test_assign_then_tick_is_the_whole_normal_path(self):
        """A lead assigns, the owner works, somebody ticks. Both write the step they name
        and both leave the changelog carrying the reason the agent supplied — which is the
        record the analysis pass reads, and the only place the old shape of the plan survives.
        """
        self.plan("write it", "review it")
        self.as_agent("lead-1")
        self.ok("plugin", "plans", "assign", "s-1", "w1", "--reason", "w1 knows this file")
        shown = self.ok("plugin", "plans", "tick", "s-1", "--reason", "the diff is in")

        self.assertEqual(self.step("s-1")["owner"], "w1")
        self.assertEqual(self.step("s-1")["progress"], "done")
        self.assertEqual(self.step("s-2")["progress"], "open")   # only the step it named
        self.assertIn("s-1", shown)
        self.assertIn("done", shown)

        self.assertEqual(self.actions(), ["create", "assign", "tick"])
        entries = self.data("plugin", "plans", "changelog", "p-1")
        self.assertEqual(entries[1]["reason"], "w1 knows this file")
        self.assertEqual(entries[1]["by"], "lead-1")
        self.assertIn("w1", entries[1]["detail"])
        self.assertIn("open → done", entries[2]["detail"])

    def test_reassigning_overwrites_and_tells_nobody(self):
        """The design's rule, and the reason it is a rule: there is no core verb that can
        tell a running agent anything, so a notification here would be a promise this
        system cannot keep. The old name goes to the changelog and nowhere else — which
        also means this verb shells out to nothing, and that is what is asserted."""
        self.plan("write it")
        self.ok("plugin", "plans", "assign", "s-1", "w1")

        # sb's own `git rev-parse` calls are its business; what must not happen is this
        # plugin reaching for `sb` itself — an `sb tell` to the agent that lost the step.
        calls, real = [], subprocess.run
        with mock.patch("subprocess.run",
                        lambda argv, *a, **k: (calls.append(list(argv)),
                                               real(argv, *a, **k))[1]):
            self.ok("plugin", "plans", "assign", "s-1", "w2", "--reason", "w1 died")
        self.assertEqual([c for c in calls if Path(str(c[0])).name == "sb"], [])

        self.assertEqual(self.step("s-1")["owner"], "w2")
        self.assertIn("was w1", self.data("plugin", "plans", "changelog", "p-1")[2]["detail"])

    # -- skip ------------------------------------------------------------------

    def test_a_skip_without_a_reason_is_refused(self):
        """A skip is a state rather than an absence, and that is only true if the state
        arrives with a sentence explaining it. Refused before anything is read or written,
        and the refusal says why it is required rather than merely that it is."""
        self.plan("run the design gate")
        code, out, _ = self.sb("plugin", "plans", "skip", "s-1", "--json")
        self.assertEqual(code, 1)
        self.assertIn("never an absence", json.loads(out)["data"]["error"])
        self.assertEqual(self.step("s-1")["progress"], "open")
        self.assertEqual(self.actions(), ["create"])

    def test_a_skip_keeps_its_reason_where_the_state_is(self):
        """On the step as well as in the changelog. A skipped step whose reason is twenty
        lines below in the changelog is an absence again by the time anybody scans the
        plan — the board is where a bad call has to be visible to be questioned."""
        self.plan("run the design gate")
        self.ok("plugin", "plans", "skip", "s-1", "--reason", "a one-line typo fix")
        self.assertEqual(self.step("s-1")["progress"], "skipped")
        self.assertEqual(self.step("s-1")["why"], "a one-line typo fix")

        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("skipped", shown)
        self.assertIn("a one-line typo fix", shown)
        self.assertEqual(self.data("plugin", "plans", "changelog", "p-1")[1]["reason"],
                         "a one-line typo fix")

    def test_a_step_is_complete_or_skipped_and_never_both(self):
        """Structural, not checked: `progress` is one string, so the second verb replaces
        what the first wrote instead of joining it. What the changelog carries is which way
        the correction went — and the stale reason does not survive the correction, or a
        ticked step would still be carrying the sentence explaining why it was skipped."""
        self.plan("write it")
        self.ok("plugin", "plans", "skip", "s-1", "--reason", "not needed after all")
        self.ok("plugin", "plans", "tick", "s-1", "--reason", "it turned out to be needed")

        self.assertEqual(self.step("s-1")["progress"], "done")
        self.assertEqual(self.step("s-1")["why"], "it turned out to be needed")
        self.assertIn("skipped → done",
                      self.data("plugin", "plans", "changelog", "p-1")[2]["detail"])

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

    def test_a_checkpoint_is_a_reference_and_never_content(self):
        """A path, a URL or an id, and a paste is refused. The cost of the other way is not
        disk: a plan holding a copy of a brief is a second copy that goes stale, and a
        record read cold cannot tell which of the two the job actually used."""
        self.plan("write it")
        self.ok("plugin", "plans", "checkpoint", "s-1",
                "--ref", ".switchboard/briefs/pr2-verbs/brief.md", "--reason", "the brief")
        self.assertEqual([c["ref"] for c in self.step("s-1")["checkpoints"]],
                         [".switchboard/briefs/pr2-verbs/brief.md"])
        self.assertIn("briefs/pr2-verbs/brief.md", self.ok("plugin", "plans", "show", "p-1"))

        for argv, expected in (
                (("checkpoint", "s-1", "--ref", "# a brief\n\nwith its body in it"),
                 "never content"),
                (("checkpoint", "s-1"), "--ref is required")):
            with self.subTest(expected=expected):
                code, out, _ = self.sb("plugin", "plans", *argv, "--json")
                self.assertEqual(code, 1)
                self.assertIn(expected, json.loads(out)["data"]["error"])
        self.assertEqual(len(self.step("s-1")["checkpoints"]), 1)

    # -- rework, add-step, dep -------------------------------------------------

    def test_rework_bumps_the_try_count_and_reopens_the_step(self):
        """Rework is a number on the step, never an edge: a failed review sends its step
        back, and modelling that as a loop would make the plan cyclic to say something a
        counter says better. A count above one is what renders, so a first try shows no
        number at all and a second one does."""
        self.plan("write it", "review it")
        self.ok("plugin", "plans", "tick", "s-1")
        self.assertNotIn("try ", self.ok("plugin", "plans", "show", "p-1"))

        self.ok("plugin", "plans", "rework", "s-1", "--reason", "the review found a bug")
        self.assertEqual(self.step("s-1")["tries"], 2)
        self.assertEqual(self.step("s-1")["progress"], "open")
        self.assertIn("try 2", self.ok("plugin", "plans", "show", "p-1"))

        # Nothing downstream is un-ticked: the design makes that the lead's judgement, and
        # a rule here would either merge unreviewed work or throw away good review.
        self.ok("plugin", "plans", "rework", "s-1", "--reason", "and another")
        self.assertEqual(self.step("s-1")["tries"], 3)
        self.assertEqual(self.step("s-2")["progress"], "open")
        self.assertEqual(self.actions(), ["create", "tick", "rework", "rework"])

    def test_add_step_mints_a_fresh_id_from_the_one_counter(self):
        """A step invented while the job runs is numbered from the same counter as every
        other step in the file, so "your step is s-3" names one thing across two plans. The
        reason matters more here than anywhere: rework leaves either a try count or an
        added step, and only the changelog can tell the analysis pass which happened."""
        self.plan("write it")
        self.ok("plugin", "plans", "create", "another job", "--step", "elsewhere")
        made = self.data("plugin", "plans", "add-step", "p-1", "fix", "what", "review",
                         "found", "--reason", "rework, as an added step")

        self.assertEqual(made["step"]["id"], "s-3")
        self.assertEqual(made["step"]["name"], "fix what review found")
        self.assertEqual(made["plan"], "p-1")
        self.assertEqual([s["id"] for s in self._doc()["plans"][0]["steps"]], ["s-1", "s-3"])
        self.assertEqual(self.data("plugin", "plans", "changelog", "p-1")[1]["reason"],
                         "rework, as an added step")

        code, out, _ = self.sb("plugin", "plans", "add-step", "p-9", "nowhere", "--json")
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
        self.assertEqual(self.step("s-4")["deps"], ["s-2", "s-3"])
        self.assertIn("after s-2, s-3", self.ok("plugin", "plans", "show", "p-1"))

        # Repeating an edge is not an error and does not double it; the plan is the same shape.
        self.ok("plugin", "plans", "dep", "s-2", "--after", "s-1")
        self.assertEqual(self.step("s-2")["deps"], ["s-1"])

        # And "already there" is decided on the NUMBER, like every other id comparison
        # here, so a bare `1` written by hand is the edge it names rather than a new one.
        doc = self._doc()
        doc["plans"][0]["steps"][2]["deps"] = ["1"]
        self._file().write_text(json.dumps(doc))
        self.ok("plugin", "plans", "dep", "s-3", "--after", "s-1")
        self.assertEqual(self.step("s-3")["deps"], ["1"])

    def test_an_edge_that_names_nothing_is_refused(self):
        """A cycle is not refused — nothing traverses an edge, so a cycle is a lead's
        mistake to read rather than a hang. An edge pointing at a step that does not exist,
        or lives in another plan, is a typo, and it renders as a wait that never ends."""
        self.plan("design", "build")
        self.ok("plugin", "plans", "create", "another job", "--step", "elsewhere")
        for argv, expected in ((("dep", "s-2", "--after", "s-9"), "no step s-9"),
                               (("dep", "s-2", "--after", "s-2"), "cannot come after itself"),
                               (("dep", "s-2", "--after", "s-3"), "is not in p-1"),
                               (("dep", "s-2",), "--after is required")):
            with self.subTest(expected=expected):
                code, out, _ = self.sb("plugin", "plans", *argv, "--json")
                self.assertEqual(code, 1)
                self.assertIn(expected, json.loads(out)["data"]["error"])
                self.assertEqual(self.step("s-2")["deps"], [])

        # And a cycle, which is allowed, stays readable rather than hanging anything.
        self.ok("plugin", "plans", "dep", "s-2", "--after", "s-1")
        self.ok("plugin", "plans", "dep", "s-1", "--after", "s-2")
        self.assertIn("after s-2", self.ok("plugin", "plans", "show", "p-1"))

    # -- what every one of them owes -------------------------------------------

    def test_every_step_verb_logs_and_none_rewrites_the_plan(self):
        """The cross-cutting rule, checked once over all eight verbs rather than eight
        times. `_write` refuses a document whose changelog is shorter than the one that was
        read, so a verb that rewrote a plan wholesale would fail here rather than quietly
        lose the story — running the whole set in sequence is what proves none of them does.
        """
        self.plan("write it", "review it")
        for argv in (("assign", "s-1", "w1"), ("tick", "s-1"),
                     ("rework", "s-1", "--reason", "again"),
                     ("skip", "s-2", "--reason", "no reviewer free"),
                     ("note", "s-1", "--text", "a note"), ("note", "p-1", "--text", "and one"),
                     ("checkpoint", "s-1", "--ref", "notes/x.md"),
                     ("add-step", "p-1", "a third"), ("dep", "s-3", "--after", "s-1")):
            with self.subTest(verb=argv[0]):
                self.ok("plugin", "plans", *argv)
        self.assertEqual(self.actions(),
                         ["create", "assign", "tick", "rework", "skip", "note", "note",
                          "checkpoint", "add-step", "dep"])
        self.assertTrue(all(e["at"] for e in self.data("plugin", "plans", "changelog", "p-1")))

    def test_a_step_verb_on_a_step_that_is_not_there_is_refused_by_name(self):
        """Ids are never reused, so "there is no s-9 yet" and "s-9 was here and is gone" are
        different things and only the first can happen — which is what makes naming the
        highest a useful thing to say rather than a leak. Reaches a machine reader too."""
        self.plan("write it")
        for argv, expected in ((("tick", "s-9"), "the highest is s-1"),
                               (("assign", "banana", "w1"), "is not a step id"),
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

    The shipped catalogue is deliberately almost bare — a merge, its review, one template —
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
        self.ok("plugin", "plans", "create", "a job")
        made = self.data("plugin", "plans", "name-step", "p-1", "merge-review",
                         "--reason", "this one is reviewed properly")

        (step,) = made["steps"]
        self.assertEqual(step["def"], "merge-review")
        self.assertEqual(step["id"], "s-1")
        self.assertIsNone(self.steps()[0]["name"])      # nothing copied into the record
        self.assertEqual(self.steps()[0]["def"], "merge-review")
        self.assertEqual(self.steps()[0]["progress"], "open")   # its own run object

        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("review the diff that is about to land", shown)
        self.assertIn("[merge-review]", shown)          # and it says that it IS a link

    def test_editing_a_definition_reaches_a_plan_already_naming_it(self):
        """The point of the link, and the design's own words: editing a library step
        reaches every plan naming it, live ones included. The plan here is mid-flight — its
        step is assigned and reworked — and the new text still arrives, because there is no
        copy in the record for the edit to have missed."""
        self.ok("plugin", "plans", "create", "a job")
        self.ok("plugin", "plans", "name-step", "p-1", "merge")
        self.ok("plugin", "plans", "assign", "s-1", "w1")
        self.ok("plugin", "plans", "rework", "s-1", "--reason", "the branch moved")

        self.define("merge", name="land the branch, once Andrew says so",
                    obliges=["merge-review"])
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
        self.ok("plugin", "plans", "create", "a job")
        self.ok("plugin", "plans", "name-step", "p-1", "merge-review")
        self.ok("plugin", "plans", "add-step", "p-1", "review it twice, it is a migration",
                "--reason", "a variant, not a forked link")

        stored = self.steps()
        self.assertEqual([s["def"] for s in stored], ["merge-review", None])
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
        self.ok("plugin", "plans", "create", "a job", "--step", "shape the work")
        made = self.data("plugin", "plans", "name-step", "p-1", "ship")

        # build, merge, and the review merge obliges — flat, in order, ids minted onwards
        # from the on-the-fly step that was already there.
        self.assertEqual([(s["id"], s["def"]) for s in made["steps"]],
                         [("s-2", "build"), ("s-3", "merge"), ("s-4", "merge-review")])
        self.assertEqual([s["def"] for s in self.steps()],
                         [None, "build", "merge", "merge-review"])
        self.assertTrue(all("steps" not in s for s in self.steps()))

    def test_a_circular_composite_is_refused(self):
        """Unlike a plan's `deps`, which nothing walks, composition IS traversed — so a
        cycle here is a hang rather than a lead's mistake to read. Refused before anything
        is written, naming the path, and the plan is untouched."""
        self.define("a", steps=["b"])
        self.define("b", steps=["a"])
        self.define("loop", steps=["loop"])
        self.ok("plugin", "plans", "create", "a job")
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
        self.assertIn("pr", listed)
        self.assertIn("ship a change as a pull request", listed)

        made = self.data("plugin", "plans", "template", "use", "pr",
                         "--title", "PR3 of the plans plugin", "--reason", "the usual shape")
        self.assertEqual(made["title"], "PR3 of the plans plugin")
        self.assertEqual(made["notes"][0]["text"][:7], "Copied ")
        # Nothing anywhere in the record points back at the template it came from.
        self.assertNotIn("template", set(made) | {k for s in made["steps"] for k in s})

        shutil.rmtree(self.catalogue("templates"))
        self.assertIn("shape the work", self.ok("plugin", "plans", "show", "p-1"))
        self.assertIn("(no templates", self.ok("plugin", "plans", "template", "list"))

    def test_a_named_step_inside_a_template_stays_a_name(self):
        """The two mechanisms meet here and must not collapse into one: the plan is a COPY,
        and the merge step inside it is still a LINK. Flattening the names into copies at
        template time would be a plan that stops tracking its definitions the moment it is
        made, which is the same bug as snapshotting and harder to see."""
        self.data("plugin", "plans", "template", "use", "pr")
        stored = self.steps()
        self.assertEqual([s["def"] for s in stored],
                         [None, None, None, "merge", "merge-review"])

        self.define("merge", name="land it, once Andrew says so", obliges=["merge-review"])
        self.assertIn("land it, once Andrew says so", self.ok("plugin", "plans", "show", "p-1"))
        self.assertIsNone(self.steps()[3]["name"])

        code, out, _ = self.sb("plugin", "plans", "template", "use", "nope", "--json")
        self.assertEqual(code, 1)
        self.assertIn("no template 'nope'", json.loads(out)["data"]["error"])

    # -- the obligation --------------------------------------------------------

    def test_adding_a_merge_step_brings_its_review_by_every_route(self):
        """Obliged, not optional. Both routes that can put a library step in a plan go
        through one expansion, so there is no argument, no template shape and no ordering
        that lands a merge without its review — and the review says which merge it belongs
        to, which is what PR7's gate will read."""
        self.ok("plugin", "plans", "create", "a job")
        self.data("plugin", "plans", "name-step", "p-1", "merge")
        self.assertEqual([(s["def"], s["obliged_by"]) for s in self.steps()],
                         [("merge", None), ("merge-review", "s-1")])

        # A second merge is a second thing to review: the dedupe is inside one act, not
        # across a plan, or the second merge would land with nothing reading its diff.
        self.data("plugin", "plans", "name-step", "p-1", "merge")
        self.assertEqual([(s["def"], s["obliged_by"]) for s in self.steps()],
                         [("merge", None), ("merge-review", "s-1"),
                          ("merge", None), ("merge-review", "s-3")])

        # And the other route in. `--reason` and nothing else: no flag turns this off.
        self.data("plugin", "plans", "template", "use", "pr")
        self.assertEqual([s["def"] for s in self.steps("p-2")][-2:], ["merge", "merge-review"])
        self.assertEqual(sorted(_plans_args("name-step")), ["--reason", "name", "plan"])

    def test_an_obliged_step_is_skipped_with_a_reason_never_omitted(self):
        """The exchange the design makes: skipping is allowed and is expected to be rare,
        and what is paid for it is a state on the board with a sentence beside it. An
        omitted step is invisible; a skipped one can be seen and questioned."""
        self.ok("plugin", "plans", "create", "a job")
        self.data("plugin", "plans", "name-step", "p-1", "merge")
        self.ok("plugin", "plans", "skip", "s-2", "--reason", "a one-line docs change")

        self.assertEqual(self.steps()[1]["progress"], "skipped")
        self.assertEqual(self.steps()[1]["why"], "a one-line docs change")
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("skipped", shown)
        self.assertIn("a one-line docs change", shown)
        self.assertIn("obliged by s-1", shown)          # still on the board, not gone

        # And it is still refused without one, on an obliged step like on any other.
        code, out, _ = self.sb("plugin", "plans", "skip", "s-2", "--json")
        self.assertEqual(code, 1)
        self.assertIn("never an absence", json.loads(out)["data"]["error"])

    def test_a_definition_that_both_composes_and_obliges_is_refused(self):
        """An obligation attaches to a step, and a composite is not a step in a plan — only
        its parts ever appear — so there is no step for `obliged_by` to name. Dropping the
        obligation instead loses one in silence, which is the single thing this mechanism
        exists to prevent, and it would be invisible to whoever wrote the file."""
        self.define("signoff", name="get a signoff")
        self.define("landing", name="land it", steps=["merge"], obliges=["signoff"])
        self.ok("plugin", "plans", "create", "a job")

        code, out, _ = self.sb("plugin", "plans", "name-step", "p-1", "landing", "--json")
        self.assertEqual(code, 1)
        self.assertIn("both composes", json.loads(out)["data"]["error"])
        self.assertEqual(self.steps(), [])

        # And it is refused when it is EXPANDED, not when the catalogue is loaded, so the
        # one bad definition takes down only what reaches it. A catalogue is edited by hand;
        # a typo in one file must not make every other definition unusable.
        self.ok("plugin", "plans", "name-step", "p-1", "merge")
        self.assertEqual([s["def"] for s in self.steps()], ["merge", "merge-review"])

        # An obligation that reaches back into its own chain is refused for the same reason
        # composition's cycle is: it is materialised, so it is walked.
        self.define("landing", name="land it", obliges=["signoff"])
        self.define("signoff", name="get a signoff", obliges=["landing"])
        code, out, _ = self.sb("plugin", "plans", "name-step", "p-1", "landing", "--json")
        self.assertEqual(code, 1)
        self.assertIn("obliges itself", json.loads(out)["data"]["error"])
        self.assertEqual([s["def"] for s in self.steps()], ["merge", "merge-review"])

    def test_every_obliging_step_gets_its_own_obliged_step(self):
        """No dedupe, anywhere: two merges are two diffs and therefore two reviews, whether
        they arrive in one act or two. Deduping would let one step's obligation be satisfied
        by a step it has nothing to do with — the door round the obligation in a tidier
        coat — and a lead who thinks one review covers both skips the second with that as
        the reason, which is visible where a dedupe would not have been."""
        self.define("land-both", name="land two branches", steps=["merge", "merge"])
        self.ok("plugin", "plans", "create", "a job")
        self.data("plugin", "plans", "name-step", "p-1", "land-both")

        self.assertEqual([(s["def"], s["obliged_by"]) for s in self.steps()],
                         [("merge", None), ("merge", None),
                          ("merge-review", "s-1"), ("merge-review", "s-2")])

    # -- a broken catalogue ----------------------------------------------------

    def test_a_broken_catalogue_file_refuses_before_it_writes_anything(self):
        """The write-then-fail bug, pinned. A verb that wrote and THEN failed to render
        would report a failure over a mutation that had already landed, and the agent that
        retried it would get a second plan or a second changelog entry. So the catalogue is
        read on the way IN, and the state file is byte-identical after a refusal."""
        self.ok("plugin", "plans", "create", "a job")
        self.data("plugin", "plans", "name-step", "p-1", "merge")
        before = self._file().read_bytes()
        (self.catalogue("library") / "broken.json").write_text("{nope")

        # p-1 names a definition, so every verb that would render it has to resolve one.
        for argv in (("tick", "s-1"), ("skip", "s-2", "--reason", "docs only"),
                     ("add-step", "p-1", "and one more"),
                     ("note", "p-1", "--text", "a note"),
                     ("name-step", "p-1", "merge"), ("template", "use", "pr"),
                     ("show", "p-1"), ("list",), ("library",)):
            with self.subTest(verb=argv[0]):
                code, out, _ = self.sb("plugin", "plans", *argv, "--json")
                self.assertEqual(code, 1)
                # And the reason reaches a machine reader, which an escaped exception did
                # not — PR4 and PR8 shell out with --json and would get nothing at all.
                self.assertIn("not readable JSON", json.loads(out)["data"]["error"])
                self.assertEqual(self._file().read_bytes(), before)

        # A broken TEMPLATE file is narrower again: it reaches the two verbs that read that
        # directory and nothing else.
        (self.catalogue("library") / "broken.json").unlink()
        (self.catalogue("templates") / "broken.json").write_text("[]")
        self.ok("plugin", "plans", "show", "p-1")
        for argv in (("template", "list"), ("template", "use", "pr")):
            with self.subTest(verb="template " + argv[1]):
                code, out, _ = self.sb("plugin", "plans", *argv, "--json")
                self.assertEqual(code, 1)
                self.assertIn("where a definition should be",
                              json.loads(out)["data"]["error"])
                self.assertEqual(self._file().read_bytes(), before)

    def test_a_broken_catalogue_file_leaves_a_plan_that_named_nothing_alone(self):
        """Refusing the verbs that resolve a definition is right; refusing `show` on a plan
        that never named one is a typo in a shipped JSON file taking down every plan in the
        repo. The catalogue is not opened at all when there is no link to resolve."""
        self.ok("plugin", "plans", "create", "a job", "--step", "just words")
        (self.catalogue("library") / "broken.json").write_text("{nope")

        for argv in (("show", "p-1"), ("list",), ("changelog", "p-1"),
                     ("tick", "s-1"), ("add-step", "p-1", "another"),
                     ("create", "a second job"), ("template", "list")):
            with self.subTest(verb=argv[0]):
                self.ok("plugin", "plans", *argv)
        self.assertEqual(self.steps()[0]["progress"], "done")

    def test_a_definition_list_written_as_a_string_is_refused_by_name(self):
        """`"obliges": "merge-review"` iterates one letter at a time. It was refused before
        this — with `'x' obliges 'm', which is not in the step library`, which is a refusal
        that sends whoever has to fix the file looking in the wrong place."""
        self.define("x", name="a step", obliges="merge-review")
        self.ok("plugin", "plans", "create", "a job")
        code, out, _ = self.sb("plugin", "plans", "name-step", "p-1", "x", "--json")
        self.assertEqual(code, 1)
        self.assertIn("read one letter at a time", json.loads(out)["data"]["error"])
        self.assertEqual(self.steps(), [])

    def test_a_definition_with_no_name_renders_as_its_own_key(self):
        """Not as "no such definition in the library", which is a lie about a file sitting
        right there and sends its reader looking for the wrong thing."""
        self.define("groundwork", about="a step somebody forgot to name")
        self.ok("plugin", "plans", "create", "a job")
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
        self.ok("plugin", "plans", "create", "a job", "--step", "write it")
        self.ok("plugin", "plans", "add-step", "p-1", "and review it")
        self.ok("plugin", "plans", "tick", "s-1")
        self.assertIn("empty", self.ok("plugin", "plans", "library"))
        self.assertIn("write it", self.ok("plugin", "plans", "show", "p-1"))

        code, out, _ = self.sb("plugin", "plans", "name-step", "p-1", "merge", "--json")
        self.assertEqual(code, 1)
        self.assertIn("the library is empty", json.loads(out)["data"]["error"])

        # A template naming a definition that is no longer there is refused too, rather
        # than copied in with a link that resolves to nothing.
        code, out, _ = self.sb("plugin", "plans", "template", "use", "pr", "--json")
        self.assertEqual(code, 1)
        self.assertIn("not in the step library", json.loads(out)["data"]["error"])


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
