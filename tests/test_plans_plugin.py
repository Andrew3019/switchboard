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
                         {"id": "s-1", "name": "write it", "progress": "open", "why": None,
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


def _plans():
    """The loaded plugin module, by the name sb imported it under."""
    return sys.modules[plugins._MODULE_PREFIX + "plans"]


if __name__ == "__main__":
    unittest.main()
