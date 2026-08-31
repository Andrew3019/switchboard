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
4. The workspace is stored at `create`, a transient miss repairs itself on a later read,
   and a branch change in the same checkout does not move an answered key.
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

import contextlib
import io
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


def _same_id(step: dict, sid: str) -> bool:
    """Is this the step that id names? By NUMBER, which is how the plugin compares ids.

    `s-1`, `step-1` and a bare `1` are one step there (`_STEP_ID`), so a test looking one up
    out of the file compares the same way — otherwise these helpers would be stricter than
    the CLI they are testing, and a test would pass or fail on a spelling no verb cares
    about. Steps mint as `step-<n>` per plan; a hand-written fixture may still say `s-<n>`.
    """
    got = re.search(r"(\d+)$", str(step.get("id") or ""))
    want = re.search(r"(\d+)$", str(sid))
    return bool(got and want and got.group(1) == want.group(1))


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

    That shell-out is also what this file used to spend most of its time on: the resolver
    asks up to two questions per `create` and every liveness read asks another, and each
    one was a fresh Python interpreter importing `switchboard.cli` from scratch — ~2-3s a
    test, ~40% of the whole suite. So `setUp` short-circuits the *process boundary* and
    nothing else (`_short_circuit_own_sb`): the same argv reaches the same `cli.main`
    against the same sandbox store, in this interpreter. It is not a fake sb — there is
    still no fake sb anywhere in here — and every subprocess to any OTHER program, the
    wedged stub `LivenessTest` writes included, is really spawned.
    """

    #: The build `_sb()` resolves to from inside the sandbox, through the `bin` symlink
    #: below. Only a call to exactly this is answered in-process.
    REAL_SB = (Path(__file__).resolve().parent.parent / "bin" / "sb").resolve()

    def setUp(self) -> None:
        super().setUp()
        (self.sw / "plugins.toml").write_text('enabled = ["plans"]\n')
        root = Path(self.tmp.name)
        (root / "bin").symlink_to(Path(__file__).resolve().parent.parent / "bin")
        self._short_circuit_own_sb()

    def _short_circuit_own_sb(self) -> None:
        """`subprocess.run([<this repo's sb>, ...])` answered by `cli.main` in this process.

        Patched at `subprocess.run` rather than at the plugin's `_ask`, because sb imports
        a plugin afresh for every command (`plugins._import`), so there is no module object
        that lives long enough to patch in `setUp`. `subprocess` is shared by every
        importer of it, and the discriminator is the resolved path of argv[0] — so the
        plugin still calls `_sb()`, still gets None when there is no build, still spends
        its `_Budget`, and a test that puts a DIFFERENT `sb` on that path gets a real fork.

        One known divergence: `as_agent()` patches `Broker.whoami` on this process, so the
        nested `cli.main` resolves to that agent, where a real fork would have resolved to
        HUMAN and scoped a caller-sensitive command (`sb status`) differently. The real-fork
        boundary test is what covers the argv the plugin builds against a real caller.
        """
        real_run = subprocess.run

        def run(argv, *a, **kwargs):
            if self._sb_is_ours(argv):
                return self._sb_in_process(list(argv)[1:], kwargs.get("cwd"))
            return real_run(argv, *a, **kwargs)

        patch = mock.patch("subprocess.run", run)
        patch.start()
        self.addCleanup(patch.stop)
        self._in_process_sb = True

    def real_sb_subprocess(self) -> None:
        """Spawn the real `sb` for the rest of this test, the way every test used to.

        For the tests whose subject IS the process boundary: what the shell-out costs, and
        that the argv this plugin builds really is answered by a real `sb` on a real store.
        """
        self._in_process_sb = False

    def _sb_is_ours(self, argv) -> bool:
        if not self._in_process_sb or isinstance(argv, (str, bytes)) or not argv:
            return False
        try:
            return Path(argv[0]).resolve() == self.REAL_SB
        except (OSError, TypeError, ValueError):
            return False

    def _sb_in_process(self, argv, cwd) -> subprocess.CompletedProcess:
        """One `sb <argv>` through `cli.main`, wearing the `CompletedProcess` the caller
        expects. Every failure is a non-zero exit and never an exception, because that is
        what the caller would have seen from a real fork of a build that crashed.

        Two deliberate simplifications, unpinned by any assertion: `timeout=` and `stdin=`
        are dropped rather than honoured, and ANY `cli.main` exception becomes exit 1 (which
        the plugin renders as `unknown`) rather than the distinct failure a real fork would
        give. Benign as things stand — of the ~305 calls this answers, ~300 exit 0 and none
        depend on a timeout — but a test that needs either would want a real fork instead."""
        out, err, here = io.StringIO(), io.StringIO(), Path.cwd()
        if cwd:
            os.chdir(cwd)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main([str(a) for a in argv])
        except SystemExit as e:                 # `sys.exit()` is an exit code out here
            code = int(e.code or 0)
        except Exception as e:                  # noqa: BLE001 — so is a traceback
            code, _ = 1, err.write(f"{type(e).__name__}: {e}\n")
        finally:
            os.chdir(here)
        return subprocess.CompletedProcess(argv, code, out.getvalue(), err.getvalue())

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
        step = next(s for pl in doc["plans"] for s in pl["steps"] if _same_id(s, sid))
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
        self.assertEqual([s["id"] for s in made["steps"]], ["step-1", "step-2"])
        # An on-the-fly step owns its words: `name` filled and `def` null. The other way
        # round is a library step, and the whole schema is asserted here so that a field
        # added by a later PR has to be added deliberately rather than noticed later.
        self.assertEqual(made["steps"][0],
                         {"id": "step-1", "name": "write it", "display": "write",
                          "def": None,
                          "obliged_by": None, "progress": "open", "why": None, "gate": None,
                          "output": None, "owner": None, "tries": 1, "notes": [], "deps": [],
                          "root": False, "checkpoints": []})
        # AUTO-CHAINED: the order the steps were typed in is an order, so `create` records
        # it rather than leaving a plan that warns about itself the moment it is made.
        self.assertEqual(made["steps"][1]["deps"], ["step-1"])
        self.assertEqual(made["display"], "board: build the plugin")
        self.assertEqual(made["notes"][0]["text"], "PR1 only")

        shown = self.ok("plugin", "plans", "show", "p-2")
        for expected in ("p-2", "build the plugin", "step-1", "step-2", "write it",
                         "test it",
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

    def test_the_resolved_workspace_survives_a_branch_change(self):
        """The key is the WORKSPACE, which is what the board groups by and what a later PR
        reads to decide a worktree is gone — not the branch, which moves under a checkout
        that has not. Once answered it is neither recomputed nor re-attached: a
        `git checkout -b` in the same directory used to make `list` go blind to the plan
        that was made there, with nothing recording that it had.

        KEPT ON A REAL FORK. The rest of this file short-circuits the process boundary for
        speed (`PlansSandbox`), which proves the resolver's logic but not that the argv it
        builds is answered by a real `sb` on a real store. This one test pays for that.
        """
        self.real_sb_subprocess()
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
        and a later read can therefore distinguish a transient miss worth retrying from a
        final answer of no workspace.

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
        with mock.patch("shutil.which",
                        lambda name, *a, **k: None if name == "sb" else real(name, *a, **k)):
            self.assertIn("(unresolved)", self.ok("plugin", "plans", "show", "p-1"))

    def test_an_unavailable_workspace_repairs_and_persists_on_read(self):
        """A creation-time outage is transient state. Once sb answers, `show` resolves
        from the plan's stored checkout and creator and writes the answer back, so later
        reads do not pay for it again."""
        (Path(self.tmp.name) / "bin").unlink()
        real = shutil.which
        with mock.patch("shutil.which",
                        lambda name, *a, **k: None if name == "sb" else real(name, *a, **k)):
            made = self.data("plugin", "plans", "create", "during an outage",
                             "--display", "board: during an outage")
        self.assertEqual(made["workspace_from"], "unavailable")

        (Path(self.tmp.name) / "bin").symlink_to(Path(__file__).resolve().parent.parent / "bin")
        self.workspace("recovered", self.repo)
        shown = self.data("plugin", "plans", "show", "p-1")
        self.assertEqual((shown["workspace"], shown["workspace_from"]),
                         ("recovered", "workspace-list"))
        stored = self._doc()["plans"][0]
        self.assertEqual((stored["workspace"], stored["workspace_from"]),
                         ("recovered", "workspace-list"))

        (Path(self.tmp.name) / "bin").unlink()
        with mock.patch("shutil.which",
                        lambda name, *a, **k: None if name == "sb" else real(name, *a, **k)):
            self.assertEqual(self.data("plugin", "plans", "show", "p-1")["workspace"],
                             "recovered")

    def test_a_failed_lazy_workspace_repair_never_breaks_the_read(self):
        """If sb still cannot answer, both human and machine views remain readable and
        the stored transient marker remains available for a future read to retry."""
        (Path(self.tmp.name) / "bin").unlink()
        real = shutil.which
        with mock.patch("shutil.which",
                        lambda name, *a, **k: None if name == "sb" else real(name, *a, **k)):
            self.data("plugin", "plans", "create", "during an outage",
                      "--display", "board: during an outage")
            self.assertIn("(unresolved)", self.ok("plugin", "plans", "show", "p-1"))
            self.assertEqual(self.data("plugin", "plans", "show", "p-1")["workspace_from"],
                             "unavailable")
        self.assertEqual(self._doc()["plans"][0]["workspace_from"], "unavailable")

    def test_ids_are_monotonic_and_never_reused(self):
        """PLAN ids are monotonic across the store and never reused — a hand-deleted plan
        must not free its number, because a changelog entry citing it stays true for the
        life of the repo. STEP ids are per plan: every plan starts at `step-1` and nothing
        another plan does moves its numbers, which is what makes two plans independent."""
        self.ok("plugin", "plans", "create", "one",
                "--display", "board: one", "--step", 'a = a', "--step", 'b = b')
        self.ok("plugin", "plans", "create", "two",
                "--display", "board: two", "--step", 'c = c')
        self.assertEqual([s["id"] for s in self.data("plugin", "plans", "show", "p-2")
                          ["steps"]], ["step-1"])

        doc = self._doc()
        doc["plans"] = [p for p in doc["plans"] if p["id"] != "p-2"]
        self._save(doc)

        made = self.data("plugin", "plans", "create", "three",
                         "--display", "board: three", "--step", 'd = d')
        self.assertEqual(made["id"], "p-3")
        self.assertEqual([s["id"] for s in made["steps"]], ["step-1"])

    def test_the_changelog_carries_the_reason_and_the_plan_cannot_be_dropped(self):
        """Written by the command, with the reason the agent supplied. A plan is reshaped
        as the job runs, and without this the file keeps only the final shape.

        WHAT IS PROTECTED IS THE PLAN AND NOT THE CHANGELOG, which is the half that
        changed when hand-editing became the way a plan is shaped. A write whose changelog
        had shrunk used to be refused; rewriting a plan file whole is now the ordinary way
        to change one, so that check stood in front of the interface it was protecting. A
        write that drops the plan is still refused — that loss cannot be reconstructed.
        """
        self.as_agent("w1")
        made = self.data("plugin", "plans", "create", "a job", "--display", "board: a job",
                         "--step", 'a = a', "--reason", "investigation landed")
        (entry,) = self.data("plugin", "plans", "changelog", made["id"])
        self.assertEqual(entry["by"], "w1")
        self.assertEqual(entry["action"], "create")
        self.assertEqual(entry["reason"], "investigation landed")
        self.assertIn("step-1", entry["detail"])

        # The single write is where the plan is protected: a document that has lost one is
        # refused there rather than quietly written back one plan short.
        mod = _plans()
        doc, seal = mod._read(self._dir())
        doc.update(plans=[])
        with self.assertRaises(ValueError) as caught:
            mod._write(self._dir(), doc, seal)
        self.assertIn("never erased", str(caught.exception))

        # And a rewritten changelog is NOT refused, because rewriting the file is how a
        # plan is edited now. Nothing validates the record and nothing refuses on it.
        doc, seal = mod._read(self._dir())
        doc["plans"][0]["changelog"] = []
        mod._write(self._dir(), doc, seal)
        self.assertEqual(self._doc()["plans"][0]["changelog"], [])

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

    def test_a_step_id_two_plans_share_is_the_ordinary_shape_now(self):
        """Step numbers are minted per plan, so two plans BOTH holding a `step-1` is what
        the store looks like and not corruption. The cross-file check that used to refuse
        the second file is gone with the store-wide counter; the twin-PLAN-id check it sat
        beside is not, because a plan id is still unique across the store.

        What that check was for — `tick step-1` naming one plan — is addressing's job now:
        a bare id resolves while one plan holds it and refuses naming the candidates when
        two do. Pinned by `test_a_bare_step_id_two_plans_hold_is_refused_by_name`."""
        self.ok("plugin", "plans", "create", "first",
                "--display", "board: first", "--step", 'do = do it')
        self.migrate()
        self._file("p-9").write_text(json.dumps(
            {"id": "p-9", "steps": [{"id": "step-1", "name": "a twin"}]}))
        out = self.ok("plugin", "plans", "list")
        self.assertNotIn("did not load", out)
        self.assertEqual(self.data("plugin", "plans", "show", "p-9")["steps"][0]["id"],
                         "step-1")
        self.assertEqual(self.data("plugin", "plans", "show", "p-1")["steps"][0]["id"],
                         "step-1")

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
        reading the same store-wide counter and minting the same PLAN id — so the two verbs
        that allocate one hold a lock across their mint and nothing else does. `name-step`
        held it too while step ids came from a store-wide counter; they come from the
        plan's own file now, so it takes nothing. Asserted as a pair at the same instant,
        because "no lock at all" and "the wrong lock" are different bugs."""
        self.migrate()
        self.assertEqual(self._at_write("plugin", "plans", "create", "a job",
                                        "--display", "board: a job",
                                        "--step", "write = write it"),
                         [(False, True)])
        self.assertEqual(self._at_write("plugin", "plans", "tick", "s-1"),
                         [(False, False)])
        self.assertEqual(self._at_write("plugin", "plans", "note", "s-1", "--text", "x"),
                         [(False, False)])
        self.assertEqual(self._at_write("plugin", "plans", "skip", "s-1",
                                        "--why", "not needed"),
                         [(False, False)])
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
        """`next_plan` is 12 with the highest plan at p-11 — plan ids are never reused, so
        a migration that recomputed it off what is present would be free to hand out one a
        deleted plan once had.

        `next_step` comes across too and is VESTIGIAL: nothing mints from it any more, and
        it is written for an un-migrated store and for an older plugin on the same repo. A
        migrated plan mints from its own file instead — one past ITS highest step, which is
        `s-3` on p-2 — and a plan made after the migration starts at `step-1` however high
        the old counter stood."""
        self.legacy()
        self.migrate()
        self.assertEqual(self.data("plugin", "plans", "create", "a fresh one",
                                   "--display", "board: a fresh one")["id"],
                         "p-12")
        meta = json.loads((self._dir() / "_meta.json").read_text())
        self.assertEqual(meta["format"], 2)
        self.assertEqual(meta["next_step"], 61)
        self.define("scan", name="scan the code", display="scan")
        made = self.data("plugin", "plans", "name-step", "p-12", "scan",
                         "--reason", "because")
        self.assertEqual(made["steps"][0]["id"], "step-1")
        old = self.data("plugin", "plans", "name-step", "p-2", "scan",
                        "--reason", "because")
        self.assertEqual(old["steps"][0]["id"], "step-4")

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

    def steps(self, plan: str = "p-1") -> list[dict]:
        """One plan's steps in order, read back out of the store."""
        return self.data("plugin", "plans", "show", plan)["steps"]

    def step(self, sid: str) -> dict:
        """One step, read back out of the file rather than out of a verb's own answer."""
        return next(s for p in self._doc()["plans"] for s in p["steps"]
                    if _same_id(s, sid))

    def actions(self, plan: str = "p-1") -> list[str]:
        return [e["action"] for e in self.data("plugin", "plans", "changelog", plan)]

    # -- advisory strategy -----------------------------------------------------

    def test_a_complete_strategy_round_trips_and_renders_as_a_nested_block(self):
        strategy = {
            "continuity": "main agent continues",
            "orchestration": "single-agent implementation with a fresh reviewer afterward",
            "model": "standard for implementation; strong and fresh for review",
            "resources": {"skills": ["github"], "presets": [], "tools": ["pytest"]},
            "isolation": "shared unless parallel tracked writes become useful",
            "budget": {"context": "about half of one main-agent context",
                       "passes": "one implementation and one correction pass"},
            "verification": "focused evidence during work; one final suite",
            "replan_if": "scope expands or the approach becomes ambiguous",
            "brief": ".switchboard/briefs/p-42/implementation.md",
        }
        self.plan("write it")
        self.edit_step("step-1", strategy=strategy)

        shown = self.data("plugin", "plans", "show", "p-1")
        self.assertEqual(shown["steps"][0]["strategy"], strategy)
        rendered = self.ok("plugin", "plans", "show", "p-1")
        for expected in ("strategy", "continuity  main agent continues", "resources",
                         "skills", "- github", "budget", "context  about half"):
            self.assertIn(expected, rendered)
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

    def test_a_step_without_strategy_keeps_the_existing_render_and_validates_cleanly(self):
        self.plan("write it")
        rendered = self.ok("plugin", "plans", "show", "p-1")
        self.assertNotIn("strategy", rendered)
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

    def test_invalid_strategy_warns_without_refusing_or_discarding_it(self):
        strategy = {"continuity": ["not text"], "invented": "preserve me"}
        self.plan("write it")
        self.edit_step("step-1", strategy=strategy)

        code, warning, _ = self.sb("plugin", "plans", "validate", "p-1")
        self.assertEqual(code, 0)
        self.assertIn("strategy.continuity must be string", warning)
        self.assertIn("replace it with a string value or remove it", warning)
        self.assertIn("strategy.invented is not a recognized strategy field", warning)
        self.assertIn("remove it or use a field named in the strategy schema", warning)
        said = self.data("plugin", "plans", "validate", "p-1")
        self.assertFalse(said["ok"])
        self.assertEqual(self.data("plugin", "plans", "show", "p-1")
                         ["steps"][0]["strategy"], strategy)
        self.assertEqual(self.step("step-1")["strategy"], strategy)

    def test_nested_strategy_schema_keywords_warn_without_discarding_data(self):
        strategy = {"resources": {"skills": ["", "a", "a"]}, "brief": "x\ny"}
        self.plan("write it")
        self.edit_step("step-1", strategy=strategy)

        code, warning, _ = self.sb("plugin", "plans", "validate", "p-1")
        self.assertEqual(code, 0)
        self.assertIn("strategy.resources.skills[0] must contain at least 1 character",
                      warning)
        self.assertIn("strategy.resources.skills must contain unique items", warning)
        self.assertIn("strategy.brief does not match", warning)
        self.assertEqual(self.data("plugin", "plans", "show", "p-1")
                         ["steps"][0]["strategy"], strategy)

        self.edit_step("step-1", strategy={"brief": "path.md\n"})
        self.assertIn("strategy.brief does not match",
                      self.ok("plugin", "plans", "validate", "p-1"))

        self.edit_step("step-1", strategy={"brief": "path.md"})
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

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
        self.assertIn("step-1", shown)
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
        self.assertIn("step-1", said)
        self.assertIn("never content", said)
        self.assertIn("point the checkpoint at the file", said)
        # A warning and not a refusal: the plan still reads, and a tick on it still lands.
        self.ok("plugin", "plans", "show", "p-1")
        self.ok("plugin", "plans", "tick", "s-1")
        self.assertEqual(self.step("s-1")["progress"], "done")

    def test_a_hand_written_note_or_checkpoint_is_read_as_the_value_it_plainly_is(self):
        """A verb appends `{text, by, at}`; a hand types the sentence. Both arrive, because
        hand-editing the file IS the interface — so a bare string is rendered as the note
        it obviously is, with no author and no time, rather than crashing every rendering
        of the plan that carries it. `_check` refuses those lists for not being LISTS and
        does not police what is inside one: a wrong record costs one rendering, and
        refusing the file over it would lose the lead the steps that are fine."""
        self.plan("write it")
        self.edit_step("s-1", notes=["the parser was the hard part"],
                       checkpoints=["notes/the-brief.md"])

        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("note  the parser was the hard part", shown)
        self.assertIn("ref   notes/the-brief.md", shown)
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))
        # Still a plan a verb can move: the fallback is a rendering and not a repair.
        self.ok("plugin", "plans", "tick", "s-1")

    def test_a_bare_plan_level_note_renders_too(self):
        """The plan's own notes are the same shape and the same hand, so they get the same
        fallback — pinned separately because they are a second call site and a fix that
        reached only the step would leave `show` crashing on the plan."""
        self.plan("write it")
        doc = self._doc()
        doc["plans"][0]["notes"] = ["this job was mostly reading"]
        self._save(doc)

        self.assertIn("this job was mostly reading",
                      self.ok("plugin", "plans", "show", "p-1"))
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

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

    def test_a_step_added_by_hand_is_numbered_from_the_plans_own_counter(self):
        """A step invented while the job runs is written into the file, and the plan's own
        counter is what numbers it — `next_step`, floored on read by the highest id really
        present, so a hand-written step and a minted one can never collide.

        The verb that used to do this is gone: it set two fields on a new object, which is
        what writing the object does. What it bought over the edit was the changelog entry
        nothing asks for any more."""
        self.plan("write it")
        doc = self._doc()
        plan = doc["plans"][0]
        plan["steps"].append({"id": f"step-{plan['next_step']}", "name": "fix what review "
                              "found", "display": "fix", "progress": "open",
                              "deps": ["step-1"]})
        plan["next_step"] += 1
        self._save(doc)

        self.assertEqual([s["id"] for s in self.steps()], ["step-1", "step-2"])
        self.assertEqual(self.steps()[1]["name"], "fix what review found")
        # And the next MINT does not hand out a number the hand-edit already used.
        self.define("scan", name="scan the code", display="scan")
        made = self.data("plugin", "plans", "name-step", "p-1", "scan")
        self.assertEqual(made["steps"][0]["id"], "step-3")

    def test_skip_writes_the_state_and_the_reason_and_refuses_without_one(self):
        """`tick`'s sibling, and the second of the two verbs that move a step past.

        A skip is a STATE WITH A SENTENCE BESIDE IT and never an absence, which is why the
        reason is not optional: a skipped step with an empty `why` draws red, so a verb
        that let one through would be a verb whose whole output is a warning. Refused at
        the door instead, where the message can say what to write.

        Child-usable like `tick`, and for the same reason: the agent that found the step
        unnecessary is the one that knows why, and it may not edit the plan's shape.
        """
        self.plan("write it", "review it")
        made = self.data("plugin", "plans", "skip", "s-1",
                         "--why", "the change is a typo", "--reason", "too small to gate")
        self.assertEqual(made["step"]["progress"], "skipped")
        self.assertEqual(self.step("s-1")["progress"], "skipped")
        self.assertEqual(self.step("s-1")["why"], "the change is a typo")
        # The step says the state and the reason together, which is the whole point of
        # `why` living on the step rather than in the changelog.
        self.assertIn("the change is a typo", self.ok("plugin", "plans", "show", "p-1"))
        entry = self.data("plugin", "plans", "changelog", "p-1")[-1]
        self.assertEqual(entry["action"], "skip")
        self.assertEqual(entry["reason"], "too small to gate")

        code, out, _ = self.sb("plugin", "plans", "skip", "s-2", "--json")
        self.assertEqual(code, 1)
        self.assertIn("--why is required", json.loads(out)["data"]["error"])
        self.assertEqual(self.step("s-2")["progress"], "open")   # and nothing moved

    def test_a_skip_releases_what_waited_on_it_exactly_as_a_tick_does(self):
        """The two words are the same fact to whatever came next: the step is not going to
        be worked again, so what waited on it is waiting no longer.

        A skip that printed nothing would leave its successor unclaimed — the agent that
        skipped a step would be the one agent never handed the next one, which is the whole
        of what `_next` is for. Asserted through the release rather than through the flag,
        so the claim survives the plumbing being rewritten.
        """
        self.plan("write it", "review it")
        said = self.ok("plugin", "plans", "skip", "s-1", "--why", "the change is a typo")
        self.assertIn("next — this move unblocked:", said)
        self.assertIn("review it", said.split("unblocked:")[1])
        released = json.loads(self.ok("plugin", "plans", "skip", "s-1",
                                      "--why", "the change is a typo", "--json"))
        self.assertEqual([s["id"] for s in released["data"]["next"]], ["step-2"])

    def test_a_progress_word_too_long_for_its_column_still_keeps_a_gap(self):
        """`step-4   waiting on Andrewget the intended change approved` was the render.

        `progress` is an OPEN vocabulary — a hand-edit is where a word like this comes
        from, and `waiting on Andrew` is sixteen characters against a ten-wide column — so
        the column pads a short value and could do nothing at all about a long one, and the
        state ran straight into the step name with nothing between them. Same defect the
        library key column already had, and the same fix: two spaces are the floor.

        Both halves are asserted, because either alone would let the other back: a long
        word keeps its gap, and a short one still starts the name where it always did."""
        self.plan("design", "build")
        self.edit_step("s-1", progress="waiting on Andrew")
        shown = self.ok("plugin", "plans", "show", "p-1")

        self.assertIn("waiting on Andrew  design", shown)
        self.assertNotIn("waiting on Andrewdesign", shown)
        self.assertIn("open      build", shown)

    def test_an_edge_is_a_field_and_show_renders_what_the_file_says(self):
        """Fan-out and join, stored as data. Nothing traverses these, waits on them or
        orders anything by them — a join waits because the lead does not start it. So the
        whole of an edge is that it is stored, rendered, and points at a step that is
        really there.

        Written into the file now. The verb that wrote one set a list, and its refusal —
        an edge naming nothing — outlived it in `_wrong`, which reaches a hand-edit where
        the verb never could."""
        self.plan("design", "build", "review", "merge")
        self.edit_step("s-4", deps=["step-3", "step-2"])
        self.assertEqual(self.step("s-2")["deps"], ["step-1"])   # what `create` chained
        self.assertIn("after step-3, step-2", self.ok("plugin", "plans", "show", "p-1"))

        # An id is read by NUMBER everywhere here, so a bare `1` written by hand is the
        # edge it names rather than an edge to nothing.
        self.edit_step("s-3", deps=["1"])
        said = self.ok("plugin", "plans", "validate", "p-1")
        self.assertNotIn("not a step in this plan", said)

    def test_an_edge_that_names_nothing_is_reported_rather_than_refused(self):
        """A cycle is not reported — nothing traverses an edge, so a cycle is a lead's
        mistake to read rather than a hang. An edge pointing at a step that does not
        exist, or at the step itself, is a typo, and it renders as a wait that never ends.

        A WARNING AND NOT A REFUSAL, like everything else in that door: the file is meant
        to be edited, and a plan that would not load because one edge reads wrong is a file
        nobody dares open. What the removed verb refused, the file now says out loud."""
        self.plan("design", "build")
        self.edit_step("s-2", deps=["step-9"])
        said = self.ok("plugin", "plans", "validate", "p-1")
        self.assertIn("step-9, which is not a step in this plan", said)

        self.edit_step("s-2", deps=["step-2"])
        self.assertIn("comes after itself", self.ok("plugin", "plans", "validate", "p-1"))

        # And a cycle, which is allowed, stays readable and is not reported.
        self.edit_step("s-1", deps=["step-2"])
        self.edit_step("s-2", deps=["step-1"])
        said = self.ok("plugin", "plans", "validate", "p-1")
        self.assertNotIn("not a step in this plan", said)
        self.assertIn("after step-2", self.ok("plugin", "plans", "show", "p-1"))

    def test_a_done_step_whose_dep_is_still_open_is_reported(self):
        """A dep is the plan's only statement of order, so a step TICKED done while a step
        it waits on is still open is either mis-ticked or mis-deped — the shape a human
        catches only by seeing green downstream of grey on the board, which nothing named
        before this. Reported, never refused, like everything in that door.

        It is about the TICK — a claim the step is finished — and not about WHEN work
        happened: running a step ahead of its deps is legitimate and warns on nothing (the
        guide's DEPS SAY WHEN A STEP RUNS), and a dep that is itself done or skipped is in
        order and reported on nothing."""
        self.plan("build", "review", "merge")
        self.edit_step("s-2", progress="done")          # review done, build (its dep) open
        said = self.ok("plugin", "plans", "validate", "p-1")
        self.assertIn("ticked done while step-1, which it waits on, is still open", said)

        # A dep that is itself done or skipped is in order, and nothing is reported.
        self.edit_step("s-1", progress="done")
        self.assertNotIn("ticked done while", self.ok("plugin", "plans", "validate", "p-1"))
        self.edit_step("s-1", progress="skipped", why="folded into the review")
        self.assertNotIn("ticked done while", self.ok("plugin", "plans", "validate", "p-1"))

    # -- what every one of them owes -------------------------------------------

    def test_every_step_verb_logs_and_none_rewrites_the_plan(self):
        """The cross-cutting rule, checked once over every mutating verb rather than once
        each. Every one of them appends its own entry and none of them rewrites a plan
        wholesale — running the whole set in sequence is what proves it, since a verb that
        rewrote the plan would take the entries before it with it.
        """
        self.plan("write it", "review it")
        for argv in (("tick", "s-1"),
                     ("note", "s-1", "--text", "a note"), ("note", "p-1", "--text", "and one"),
                     ("skip", "s-2", "--why", "covered by the first"),
                     ("name-step", "p-1", "merge")):
            with self.subTest(verb=argv[0]):
                self.ok("plugin", "plans", *argv)
        self.assertEqual(self.actions(),
                         ["create", "tick", "note", "note", "skip", "name-step"])
        self.assertTrue(all(e["at"] for e in self.data("plugin", "plans", "changelog", "p-1")))

    # -- per-plan numbering, and the addressing that pays for it ---------------

    def test_every_plan_numbers_its_own_steps_from_one(self):
        """Two plans are completely independent: both start at `step-1`, and what one does
        to its steps moves nothing in the other. The counter is in the plan's own file, so
        this holds across the split store rather than through a shared sidecar — and a plan
        made before this keeps its `s-<n>` ids and mints one past its OWN highest."""
        self.plan("write it", "review it")
        self.ok(*_create("another job", "elsewhere"))
        self.assertEqual([s["id"] for s in self.steps()], ["step-1", "step-2"])
        self.assertEqual([s["id"] for s in self.steps("p-2")], ["step-1"])

        self.define("scan", name="scan the code", display="scan")
        self.ok("plugin", "plans", "name-step", "p-2", "scan", "--reason", "the job grew")
        self.assertEqual([s["id"] for s in self.steps("p-2")], ["step-1", "step-2"])
        self.assertEqual([s["id"] for s in self.steps()], ["step-1", "step-2"])
        self.migrate()
        self.assertEqual(json.loads(self._file("p-2").read_text())["next_step"], 3)

        # An old plan, hand-written the way the store held them before this: nothing is
        # renumbered and the next mint is one past its own highest, in the new spelling.
        old = {"id": "p-9", "title": "an old one", "checkout": str(self.repo),
               "steps": [{"id": "s-84", "name": "done long ago", "progress": "open"}],
               "changelog": [], "notes": []}
        self._file("p-9").write_text(json.dumps(old))
        made = self.data("plugin", "plans", "name-step", "p-9", "scan",
                         "--reason", "still running")
        self.assertEqual(made["steps"][0]["id"], "step-85")
        self.assertEqual([s["id"] for s in self.steps("p-9")], ["s-84", "step-85"])

    def test_a_bare_step_id_two_plans_hold_is_refused_by_name(self):
        """The trade per-plan numbering makes, in one test. A bare id is what an agent is
        told at spawn and types, and it resolves while one plan holds that number — which
        is almost always, since a worktree almost always holds one plan. When two do, the
        refusal names the candidates and the spelling that works rather than picking one:
        a tick landing on the wrong plan's step is the failure this cannot have."""
        self.plan("write it")
        code, out, _ = self.sb("plugin", "plans", "tick", "step-1", "--json")
        self.assertEqual(code, 0)                       # one plan holds it: it resolves

        self.ok(*_create("another job", "elsewhere"))
        code, out, _ = self.sb("plugin", "plans", "tick", "step-1", "--json")
        self.assertEqual(code, 1)
        said = json.loads(out)["data"]["error"]
        self.assertIn("p-1", said)
        self.assertIn("p-2", said)
        self.assertIn("name the plan", said)
        # Refused means nothing moved, in either plan.
        self.assertEqual(self.steps("p-2")[0]["progress"], "open")

    def test_a_qualified_id_names_the_plan_and_every_step_verb_takes_one(self):
        """`p-2/step-1` is the spelling that always works, and it is one argument rather
        than a flag, on every verb that takes a step. The qualifier names the plan for
        one of them — `tick`, `skip` and `note` all take a step where they always did."""
        self.plan("write it")
        self.ok(*_create("another job", "design", "build"))

        self.ok("plugin", "plans", "tick", "p-2/step-1", "--reason", "shaped")
        self.assertEqual(self.steps("p-2")[0]["progress"], "done")
        self.assertEqual(self.steps()[0]["progress"], "open")   # p-1's own step-1, untouched

        self.ok("plugin", "plans", "note", "p-2/step-2", "--text", "picked up")
        self.assertEqual(self.steps("p-2")[1]["notes"][0]["text"], "picked up")

        self.ok("plugin", "plans", "skip", "p-2/step-2", "--why", "already covered")
        self.assertEqual(self.steps("p-2")[1]["progress"], "skipped")
        self.assertEqual(self.steps()[0]["progress"], "open")   # p-1's step-1, still not

        # And `show` takes one too, which is how a step's own instructions are asked for.
        self.assertIn("build", self.ok("plugin", "plans", "show", "p-2/step-2"))

    def test_a_step_verb_on_a_step_that_is_not_there_is_refused_by_name(self):
        """Ids are never reused within a plan, so "there is no step-9 yet" and "step-9 was
        here and is gone" are different things and only the first can happen — which is
        what makes naming the highest a useful thing to say rather than a leak. Reaches a
        machine reader too.

        The highest is PER PLAN now, so a qualified id says which plan it looked in and a
        bare one that no plan holds falls back to the highest anywhere."""
        self.plan("write it")
        for argv, expected in ((("tick", "s-9"), "the highest is step-1"),
                               (("tick", "p-1/step-9"),
                                "no step step-9 in p-1 — the highest there is step-1"),
                               (("note", "banana", "--text", "x"), "is not a step id"),
                               (("note", "s-9", "--text", "x"), "the highest is step-1")):
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

    The shipped catalogue is deliberately almost bare — `change-approval`, `create-pr`,
    `merge`, `merge-human-review`, `plan-review`, `review`, one template —
    so most of these write their own definitions into the sandbox's `defaults/`, which is
    also the honest way to test a catalogue whose contents PR9 is supposed to grow.

    Unproven here: that a lead reaches for the library at all rather than typing the step,
    which is a workflow question; and that the shipped catalogue is the right one, which the
    design says is read off real runs rather than decided now.
    """

    def steps(self, plan: str = "p-1") -> list[dict]:
        """The steps as STORED, not as rendered — the difference is the whole subject."""
        return next(p for p in self._doc()["plans"] if p["id"] == plan)["steps"]

    @contextlib.contextmanager
    def github_comments(self, *, pulls=(42, 181)):
        """A PR's issue comments behind the real `gh api` argv the plugin builds.

        This fakes GitHub, not sb or herdr: every plans command still crosses the normal
        plugin dispatch and rendering path. The list response has the nested shape
        `gh api --paginate --slurp` emits, while POST and PATCH consume the JSON stdin the
        production command sends and return GitHub's numeric issue-comment id.
        """
        comments: list[dict] = []
        next_id = 100
        real_run = subprocess.run

        def run(argv, *args, **kwargs):
            nonlocal next_id
            if list(argv[:2]) != ["gh", "api"]:
                return real_run(argv, *args, **kwargs)
            pull = next((str(arg) for arg in argv if "/pulls/" in str(arg)), None)
            if pull is not None:
                number = int(pull.rsplit("/", 1)[-1])
                if number not in pulls:
                    return subprocess.CompletedProcess(argv, 1, "", "HTTP 404: Not Found")
                stdout = json.dumps({"number": number})
            elif "--paginate" in argv:
                stdout = json.dumps([comments])
            else:
                body = json.loads(kwargs["input"])["body"]
                method = argv[argv.index("--method") + 1]
                if method == "POST":
                    row = {"id": next_id, "body": body}
                    next_id += 1
                    comments.append(row)
                else:
                    cid = int(str(argv[argv.index("--method") + 2]).rsplit("/", 1)[-1])
                    row = next(row for row in comments if row["id"] == cid)
                    row["body"] = body
                stdout = json.dumps(row)
            return subprocess.CompletedProcess(argv, 0, stdout, "")

        with mock.patch("subprocess.run", side_effect=run):
            yield comments

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
        self.assertEqual(step["id"], "step-1")
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
        """There is no verb that forks a definition for one job, and this is what stands
        in for one: a step of your own words, written into the file. The two live side by
        side in one plan — one owning its words, one owning a link — which is what "both
        are first class" means."""
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.ok("plugin", "plans", "name-step", "p-1", "merge-human-review")
        doc = self._doc()
        plan = doc["plans"][0]
        plan["steps"].append({"id": "step-2", "name": "review it twice, it is a migration",
                              "display": "review", "progress": "open", "def": None,
                              "deps": ["step-1"]})
        plan["next_step"] = 3
        self._save(doc)

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
        self.define("merge", name="merge it", obliges=["merge-human-review"])
        self.define("ship", steps=["build", "merge"])
        self.ok("plugin", "plans", "create", "a job",
                "--display", "board: a job", "--step", 'shape = shape the work')
        made = self.data("plugin", "plans", "name-step", "p-1", "ship")

        # build, merge, and the review merge obliges — flat, in order, ids minted onwards
        # from the on-the-fly step that was already there.
        self.assertEqual([(s["id"], s["def"]) for s in made["steps"]],
                         [("step-2", "build"), ("step-3", "merge"), ("step-4", "merge-human-review")])
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
                         [None, None, None, None, "create-pr", "change-approval",
                          "merge-human-review", "review", "merge"])

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

    def test_the_shipped_template_is_a_worked_example_of_every_field_a_step_carries(self):
        """What the template is FOR, past the steps: a step carries a gate, an owner, a
        checkpoint, a skip with its reason, a count of tries and its own output, and not
        one of those has a verb — they arrive by editing the file. A template that could
        carry only a name would leave the shape of a step documented nowhere it can be
        read, so an entry's other keys are copied onto the step it mints.

        ONE WORKED EXAMPLE OF EACH, spread across the steps, and not every step carrying
        every field: a plan where every step has a gate is not what a plan looks like.
        The copy still validates clean — a skip has its reason, and the gate is on a step
        nobody has ticked."""
        self.data("plugin", "plans", "template", "use", "docs")
        stored = self.steps()

        self.assertEqual([c["ref"] for c in stored[0]["checkpoints"]],
                         ["design/PLANS-AND-STEPS.md"])
        self.assertTrue(stored[1]["owner"])
        self.assertIn("Claims checked", stored[1]["output"])
        self.assertEqual(stored[2]["tries"], 2)
        # A note is a record, so the sentence a template author writes is turned into one
        # rather than copied through as a bare string a renderer would trip over.
        self.assertIn("redone as a cut", stored[2]["notes"][0]["text"])
        self.assertEqual(stored[3]["progress"], "skipped")
        self.assertTrue(stored[3]["why"])
        # On the entry's own step and never on another named step's obligations: the gate
        # belongs to the merge entry.
        merge = next(s for s in stored if s.get("def") == "merge")
        self.assertIn("Andrew", merge["gate"])
        self.assertTrue(all(s["gate"] is None for s in stored if s is not merge))

        shown = self.ok("plugin", "plans", "show", "p-1")
        for text in ("design/PLANS-AND-STEPS.md", "Claims checked", "try 2",
                     "redone as a cut", "skipped", "nothing here to run", "gate"):
            self.assertIn(text, shown)
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

        # `id` and `deps` are the minter's, whatever a template writes: the numbering and
        # the edges `after` draws are not a field an entry gets to author.
        d = self.catalogue("templates")
        (d / "forged.json").write_text(json.dumps(
            {"title": "t", "display": "board: t",
             "steps": [{"name": "one", "display": "one"},
                       {"name": "two", "display": "two", "after": [1],
                        "id": "step-99", "deps": ["step-40"]}]}))
        made = self.data("plugin", "plans", "template", "use", "forged")
        self.assertEqual([s["id"] for s in made["steps"]], ["step-1", "step-2"])
        self.assertEqual(made["steps"][1]["deps"], ["step-1"])

    # -- the obligation --------------------------------------------------------

    def test_adding_a_create_pr_step_brings_its_human_list_by_every_route(self):
        """Obliged, not optional. Both routes that can put a library step in a plan go
        through one expansion, so there is no argument, no template shape and no ordering
        that opens a PR without its human list — and the list says which PR it belongs to."""
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.data("plugin", "plans", "name-step", "p-1", "create-pr")
        self.assertEqual([(s["def"], s["obliged_by"]) for s in self.steps()],
                         [("create-pr", None), ("change-approval", "step-1"),
                          ("merge-human-review", "step-1"), ("review", "step-2")])

        # A second PR is a second human-facing candidate: nothing reuses the first list.
        self.data("plugin", "plans", "name-step", "p-1", "create-pr")
        self.assertEqual([(s["def"], s["obliged_by"]) for s in self.steps()],
                         [("create-pr", None), ("change-approval", "step-1"),
                          ("merge-human-review", "step-1"), ("review", "step-2"),
                          ("create-pr", None), ("change-approval", "step-5"),
                          ("merge-human-review", "step-5"), ("review", "step-6")])

        # And the other route in. `--reason` and nothing else: no flag turns this off.
        self.data("plugin", "plans", "template", "use", "docs")
        template = self.steps("p-2")
        pr = next(s for s in template if s.get("def") == "create-pr")
        human = next(s for s in template if s.get("def") == "merge-human-review")
        self.assertEqual(human["obliged_by"], pr["id"])
        self.assertEqual(sorted(_plans_args("name-step")), ["--reason", "name", "plan"])

    def test_an_obliged_step_is_skipped_with_a_reason_never_omitted(self):
        """The exchange the design makes: skipping is allowed and is expected to be rare,
        and what is paid for it is a state on the board with a sentence beside it. An
        omitted step is invisible; a skipped one can be seen and questioned."""
        self.define("merge", name="merge", obliges=["merge-human-review"])
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.data("plugin", "plans", "name-step", "p-1", "merge")
        self.edit_step("s-2", progress="skipped", why="a one-line docs change")

        self.assertEqual(self.steps()[1]["progress"], "skipped")
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("skipped", shown)
        self.assertIn("a one-line docs change", shown)
        self.assertIn("obliged by step-1", shown)          # still on the board, not gone

        # And one without a reason is still called out, on an obliged step like on any
        # other — as a warning now rather than a refusal, since nothing can refuse a file.
        self.edit_step("s-2", why=None)
        self.assertIn("never an absence", self.ok("plugin", "plans", "validate", "p-1"))

    # -- change approval and review, the shipped pair ---------------------------

    def test_naming_create_pr_lands_approval_reviews_and_human_checks_in_one_act(self):
        """The chain the landing shape depends on: `create-pr` obliges `change-approval`,
        which obliges `review`, while the PR also obliges the human checklist. `_mint`
        walks obligations TRANSITIVELY — so an agent that names the one step it knows it needs gets the gate and the review it did not
        think of, in the same act. That transitive walk is the whole mechanism here: a
        one-level walk would land the gate and silently lose the review under it."""
        self.ok(*_create("ship a change", "write the code"))
        self.data("plugin", "plans", "name-step", "p-1", "create-pr")

        self.assertEqual([(s["def"], s["obliged_by"]) for s in self.steps()],
                         [(None, None), ("create-pr", None),
                          ("change-approval", "step-2"),
                          ("merge-human-review", "step-2"),
                          ("review", "step-3")])
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("get the intended change approved before implementing it", shown)
        self.assertIn("review the implementation", shown)

    def test_review_stands_alone_and_pulls_in_no_change_approval(self):
        """The constraint from the other side: a plan may have a review with no approval
        gate in front of it, and that is a plain review rather than half a pair. `review`
        obliges nothing, so naming it lands ONE step — which is what makes the obligation
        run one way only, and reversing it would make a plain review impossible to ask
        for."""
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.data("plugin", "plans", "name-step", "p-1", "review")

        self.assertEqual([s["def"] for s in self.steps()], ["review"])
        self.assertNotIn("change-approval", self._raw())

    def test_naming_create_pr_twice_lands_eight_steps_and_never_four(self):
        """No dedupe, for the new group as for the old one. Two PRs are two diffs and
        therefore two contracts, reviews and human lists; a dedupe would let one approval stand for
        a change it never saw. A lead who thinks one covers both skips the second with
        that as the reason, which is visible where a dedupe was not."""
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.data("plugin", "plans", "name-step", "p-1", "create-pr")
        self.data("plugin", "plans", "name-step", "p-1", "create-pr")

        self.assertEqual([s["def"] for s in self.steps()],
                         ["create-pr", "change-approval", "merge-human-review", "review",
                          "create-pr", "change-approval", "merge-human-review", "review"])
        self.assertEqual([s["obliged_by"] for s in self.steps()],
                         [None, "step-1", "step-1", "step-2",
                          None, "step-5", "step-5", "step-6"])

    def test_each_of_the_landing_four_is_skipped_with_a_reason_never_omitted(self):
        """The exchange, on the group that will meet it most: a contract for a typo and a
        review or manual pass on a one-line docs change are skips somebody should be able to make.
        What is paid is a state on the board with a sentence beside it — so all four skip
        clean, and none of them can be left out in the first place."""
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.data("plugin", "plans", "name-step", "p-1", "create-pr")

        for sid, why in (("s-1", "no PR, this lands on main"),
                         ("s-2", "a one-line typo fix needs no contract"),
                         ("s-3", "the typo needs no manual pass"),
                         ("s-4", "the typo was independently reviewed")):
            self.edit_step(sid, progress="skipped", why=why)
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

        shown = self.ok("plugin", "plans", "show", "p-1")
        for expected in ("no PR, this lands on main", "needs no contract",
                         "obliged by step-1", "obliged by step-2"):
            self.assertIn(expected, shown)
        # And a skip with no reason is still called out, on these like on any other step.
        self.edit_step("s-2", why=None)
        self.assertIn("never an absence", self.ok("plugin", "plans", "validate", "p-1"))

    def test_both_new_definitions_carry_a_board_label(self):
        """`name-step` and `template use` REFUSE a definition with no `display`, so a
        shipped one without it is a step nobody can add. Guarding the regression rather
        than the rule: the refusal is tested elsewhere, and what this pins is that the two
        definitions shipped in this change are on the right side of it."""
        (self.catalogue("templates") / "landing.json").write_text(json.dumps(
            {"title": "land a change", "display": "land a change",
             "steps": [{"def": "change-approval"}, {"def": "review"}]}))
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")

        for key, label in (("change-approval", "change approval"), ("review", "review")):
            self.data("plugin", "plans", "name-step", "p-1", key)
            self.assertIn(f"[board {label}]", self.ok("plugin", "plans", "show", "p-1"))
        self.ok("plugin", "plans", "template", "use", "landing")
        self.assertEqual([s["def"] for s in self.steps("p-2")],
                         ["change-approval", "review", "review"])

    def test_the_library_lists_the_new_pair_and_prints_what_naming_one_does(self):
        """The catalogue is browsed before it is named from, so what `library` says about a
        definition is the whole of what a lead knows before adding it. For these two that
        has to include the obligation — naming the approval gate adds a review as well, and
        a listing that showed only the name would make that a surprise in the plan file."""
        listed = self.ok("plugin", "plans", "library")
        self.assertIn("change-approval", listed)
        self.assertIn("get the intended change approved before implementing it", listed)
        self.assertIn("review          review the implementation", listed)

        full = self.ok("plugin", "plans", "library", "change-approval")
        self.assertIn("obliges     review", full)
        self.assertIn("never omitted", full)
        # The `about`, wrapped and printed. Read back with the wrapping flattened, because
        # what is asserted is that the prose is THERE — a phrase that lands across a line
        # break the next sentence added to the definition moves is not a fact about the
        # catalogue, and pinning it made an edit to the prose look like a broken renderer.
        flat = " ".join(full.split())
        self.assertIn("IN YOUR OWN CHAT", flat)
        self.assertIn("Scope & Objectives", flat)

    def test_change_approval_declares_its_gate_in_prose_and_never_in_the_field(self):
        """The done-gate trap, pinned on the step that would spring it. A gate on a step
        that is already DONE is a defect, and this step's whole lifecycle is gate, then
        answered, then TICKED — so a `gate` string on it would paint every landing plan red
        the moment the approval it describes was granted.

        The way out is the one `merge` already takes: the gate lives in the definition's
        prose, where the agent that has to block reads it, and the field stays null. What
        is asserted is both halves — no `gate` in the shipped JSON, and a ticked approval
        step validating clean — because either alone would let the other come back.

        Both halves are about the DEFINITION and about MINT. The definition now asks the
        plan writer to author a gate of their own on the step, and to empty it as they tick
        — see the test below — which is a sentence about this job written by hand, and is
        the opposite of a definition shipping one for every plan alike."""
        spec = json.loads((self.catalogue("library") / "change-approval.json").read_text())
        self.assertNotIn("gate", spec)
        self.assertIn("sb block", spec["about"])

        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.data("plugin", "plans", "name-step", "p-1", "change-approval")
        self.assertIsNone(self.steps()[0]["gate"])
        self.ok("plugin", "plans", "tick", "s-1", "--reason", "he approved it")
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

    def test_change_approval_asks_for_a_gate_and_for_emptying_it_at_the_tick(self):
        """The instruction and the thing that makes it safe to follow, in one test.

        Nothing minted a gate onto an approval step and nothing asked for one, so whether a
        plan structurally held the change for a human was planner-by-planner — two of four
        eval plans shipped without it. The definition asks for it now. It has to ask for
        the emptying in the same breath: this step's lifecycle is gate, answered, TICKED,
        and a gate left on a done step is a defect, so an instruction that stopped at
        "write the gate" would have painted every landing plan red from the approval on.

        Both clauses are asserted through the CLI the plan writer reads them from, and the
        red-then-clean pair below is why the second clause exists."""
        about = self.ok("plugin", "plans", "library", "change-approval")
        flat = " ".join(about.split())
        self.assertIn("`gate` field is where that sentence goes", flat)
        self.assertIn("EMPTY THE `gate` FIELD as you tick", flat)

        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.data("plugin", "plans", "name-step", "p-1", "change-approval")
        self.edit_step("s-1", gate="Andrew approves the change contract for this job.")
        self.ok("plugin", "plans", "tick", "s-1", "--reason", "he approved it")
        self.assertIn("already done", self.ok("plugin", "plans", "validate", "p-1"))

        # And the emptying the definition asks for is what clears it.
        self.edit_step("s-1", gate=None)
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

    def test_a_definition_that_both_composes_and_obliges_is_refused(self):
        """An obligation attaches to a step, and a composite is not a step in a plan — only
        its parts ever appear — so there is no step for `obliged_by` to name. Dropping the
        obligation instead loses one in silence, which is the single thing this mechanism
        exists to prevent, and it would be invisible to whoever wrote the file."""
        self.define("merge", name="merge", obliges=["merge-human-review"])
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
        self.define("merge", name="merge", obliges=["merge-human-review"])
        self.define("land-both", name="land two branches", steps=["merge", "merge"])
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.data("plugin", "plans", "name-step", "p-1", "land-both")

        self.assertEqual([(s["def"], s["obliged_by"]) for s in self.steps()],
                         [("merge", None), ("merge", None),
                          ("merge-human-review", "step-1"), ("merge-human-review", "step-2")])

    # -- a broken catalogue ----------------------------------------------------

    def test_a_broken_catalogue_file_refuses_before_it_writes_anything(self):
        """The write-then-fail bug, pinned. A verb that wrote and THEN failed to render
        would report a failure over a mutation that had already landed, and the agent that
        retried it would get a second plan or a second changelog entry. So the catalogue is
        read on the way IN, and the state file is byte-identical after a refusal."""
        self.define("merge", name="merge", obliges=["merge-human-review"])
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.data("plugin", "plans", "name-step", "p-1", "merge")
        before = self._raw()
        (self.catalogue("library") / "broken.json").write_text("{nope")

        # p-1 names a definition, so every verb that would render it has to resolve one.
        for argv in (("tick", "s-1"), ("tick", "s-2"),
                     ("skip", "s-1", "--why", "not needed"),
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
                     ("tick", "s-1"),
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


    # -- a definition's command ------------------------------------------------

    def test_a_definitions_command_reaches_the_step_that_names_it(self):
        """The command is resolved onto the step the way the name and the display are —
        rendered under it, never copied into the record. What it buys is that the agent
        working the step reads the command where the step is; a field that only appeared
        under `library <name>` would be a field somebody has to go and find, which is the
        cost it exists to remove."""
        self.define("post", name="post the plan on the pull request", display="post",
                    command='gh pr comment <PR> --body "$(sb plugin plans show <PLAN>)"')
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.ok("plugin", "plans", "name-step", "p-1", "post", "--reason", "post it")

        self.assertNotIn("command", self.steps()[0])     # nothing copied into the record
        self.assertNotIn("gh pr comment", self._raw())
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn('cmd   gh pr comment <PR> --body "$(sb plugin plans show <PLAN>)"',
                      shown)
        # And an edit to the definition reaches the plan already running, like the name.
        self.define("post", name="post the plan on the pull request", display="post",
                    command="gh pr comment <PR> --body-file <FILE>")
        self.assertIn("cmd   gh pr comment <PR> --body-file <FILE>",
                      self.ok("plugin", "plans", "show", "p-1"))

    def test_a_definition_with_no_command_renders_no_command_line(self):
        """Most steps have no one standard command, and an empty `cmd` line under them
        would say there was one. Null rather than blank, so a step that carries a command
        is legible as the exception it is."""
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.ok("plugin", "plans", "name-step", "p-1", "merge-human-review",
                "--reason", "a human checks it")

        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("list what only a human can check", shown)
        self.assertNotIn("cmd", shown)

    def test_the_two_shipped_pr_steps_carry_the_commands_that_do_them(self):
        """The pair the field was added for, and they are no longer the same command.

        `create-pr` posts the plan as one marked comment. `merge` is the landing VERB — it
        does the head comparison, the merge and the same exact-marker upsert in one act,
        rather than handing an agent the comment command and trusting it to hand-run
        `gh pr merge` beside it. Both stay on their steps with obvious placeholders.
        """
        self.ok("plugin", "plans", "create", "a job", "--display", "board: a job")
        self.data("plugin", "plans", "name-step", "p-1", "create-pr")
        self.data("plugin", "plans", "name-step", "p-1", "merge")

        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("cmd   sb plugin plans comment <PLAN> --pr <PR>", shown)
        self.assertIn("cmd   sb plugin plans merge <PLAN> --pr <PR>", shown)
        self.assertNotIn("--edit-last", shown)
        self.assertNotIn("gh pr merge", shown)
        # And the library prints each under the definition read in full, beside the prose.
        self.assertIn("command     sb plugin plans merge <PLAN> --pr <PR>",
                      self.ok("plugin", "plans", "library", "merge"))
        self.assertIn("command     sb plugin plans comment <PLAN> --pr <PR>",
                      self.ok("plugin", "plans", "library", "create-pr"))

    def test_comment_updates_the_marked_id_and_leaves_a_later_comment_unchanged(self):
        """The PR-181 sequence: the same actor writes something after the plan comment.

        Updating the actor's latest comment destroyed that intervening note. The marker
        lookup must PATCH the first comment's numeric id and leave the later body byte for
        byte unchanged, regardless of ordering or authorship.
        """
        self.data(*_create("a job", "write it"))
        with self.github_comments() as comments:
            made = self.data("plugin", "plans", "comment", "p-1", "--pr", "181")
            self.assertEqual(made["action"], "created")
            marker = made["marker"]
            self.assertIn(marker, comments[0]["body"].splitlines())
            old_plan_body = comments[0]["body"]

            later_body = "## Human review\n\nLeave this comment exactly as written.\n"
            comments.append({"id": 999, "body": later_body})
            self.ok("plugin", "plans", "tick", "p-1/step-1")
            changed = self.data("plugin", "plans", "comment", "plan-1", "--pr", "181")

        self.assertEqual(changed["action"], "updated")
        self.assertEqual(changed["comment_id"], made["comment_id"])
        self.assertNotEqual(comments[0]["body"], old_plan_body)
        self.assertEqual(comments[1]["body"], later_body)

    def test_comment_upsert_cannot_claim_a_preseeded_predictable_marker(self):
        """A planted plan-id-only marker is unrelated and remains byte-for-byte intact.

        The first upsert mints and persists an unpredictable marker; a retry finds that
        exact object and keeps one authoritative plan rendering without claiming the
        attacker's earlier comment.
        """
        self.data(*_create("a job", "write it"))
        planted = "unrelated\n\n<!-- switchboard-plan: plan-1 -->\n"
        with self.github_comments() as comments:
            comments.append({"id": 77, "body": planted})
            first = self.data("plugin", "plans", "comment", "p-1", "--pr", "42")
            second = self.data("plugin", "plans", "comment", "p-1", "--pr", "42")

        marker = first["marker"]
        marked = [row for row in comments if marker in row["body"].splitlines()]
        self.assertEqual(len(marked), 1)
        self.assertEqual(comments[0], {"id": 77, "body": planted})
        self.assertNotEqual(first["comment_id"], 77)
        self.assertEqual(second["action"], "updated")
        self.assertEqual(second["comment_id"], first["comment_id"])
        self.assertNotIn(marker, self.ok("plugin", "plans", "show", "p-1", "--markdown"))

    def test_comment_rejects_an_issue_number_that_is_not_a_pull_request(self):
        """Issue comments share an API, so the pulls endpoint must authorize the target."""
        self.data(*_create("a job", "write it"))
        with self.github_comments(pulls=()) as comments:
            code, out, _ = self.sb(
                "plugin", "plans", "comment", "p-1", "--pr", "42", "--json")

        self.assertEqual(code, 1)
        self.assertIn("404", json.loads(out)["data"]["error"])
        self.assertEqual(comments, [])
        self.assertNotIn("pr_comment_nonce", self._doc()["plans"][0])

    # -- where a named step runs, which is not what it obliges ------------------

    def test_an_anchor_puts_a_step_where_it_runs_and_not_where_it_was_named(self):
        """The bug this field was added for, on the shipped catalogue.

        `create-pr` obliges `change-approval`, which obliges `review`, and the human-only
        checklist — so naming the PR step lands four, and reading the ORDER off the obligation put the approval
        immediately before the PR. An approval is the gate before any code: it landed
        mid-chain and the lead re-deped it to the front of every plan it was ever named
        into. The obligation was right and the edge was wrong, and the anchor is the fact
        the edge was standing in for.
        """
        self.data(*_create("a job", "write it", "test it"))
        added = self.data("plugin", "plans", "name-step", "p-1", "create-pr")
        by_def = {s["def"]: s for s in added["steps"]}

        # The approval comes before the implementation, so there is nothing in the plan
        # for it to come after — a deliberate root, marked as one rather than left looking
        # like a forgotten edge.
        self.assertEqual(by_def["change-approval"]["deps"], [])
        self.assertTrue(by_def["change-approval"]["root"])
        # The review comes after the WORK, not after the approval that obliged it.
        self.assertEqual(by_def["review"]["deps"], ["step-2"])
        # The human-only list is prepared from completed evidence before the PR, not after
        # the human has already opened it.
        self.assertEqual(by_def["merge-human-review"]["deps"], ["step-2"])
        # And the PR waits on both reviews AND on the approval — the last of those is the
        # obligation, put back as an edge because the anchor drew none. See
        # `test_the_pr_waits_on_the_approval_it_obliged`.
        self.assertEqual(set(by_def["create-pr"]["deps"]),
                         {by_def["review"]["id"], by_def["merge-human-review"]["id"],
                          by_def["change-approval"]["id"]})
        self.assertNotIn("incomplete", added, f"and nothing is left to fix: {added}")

        # The merge is the landing step and waits on the PR that already carried the list.
        more = self.data("plugin", "plans", "name-step", "p-1", "merge")
        by_def = {s["def"]: s for s in more["steps"]}
        pr = next(s["id"] for s in added["steps"] if s["def"] == "create-pr")
        self.assertEqual(by_def["merge"]["deps"], [pr])

    def test_an_unanchored_definition_keeps_the_placement_it_always_had(self):
        """A repo's own library predates this field, and a catalogue that grows will hold
        definitions with no fixed place in a job. Both go on hanging off whatever the plan
        currently ends with, with the obliging step waiting on what it obliged — which is
        what makes the anchor a fix rather than a rewrite."""
        self.define("merge", name="merge the pull request", obliges=["merge-human-review"])
        self.define("merge-human-review", name="list what only a human can check")
        self.data(*_create("a job", "write it", "review it"))
        added = self.data("plugin", "plans", "name-step", "p-1", "merge")
        by_def = {s["def"]: s for s in added["steps"]}
        self.assertEqual(by_def["merge-human-review"]["deps"], ["step-2"])
        self.assertEqual(by_def["merge"]["deps"], [by_def["merge-human-review"]["id"]])
        self.assertNotIn("incomplete", added)

    def test_an_unanchored_step_obliging_an_anchored_one_is_not_a_deadlock(self):
        """The mixed library the anchor rule promises still works, and the cycle it made.

        The obligation edge was drawn whenever EITHER end was unanchored, so an unanchored
        step obliging an anchored one got the edge — and then the anchored step was placed
        after the very step now waiting on it. Two steps each waiting for the other, in a
        graph nothing traverses and nothing checks for cycles: `validate` said no defects
        and both steps were blocked for ever. The OBLIGED end alone decides now.
        """
        self.define("impl-thing", name="implement the thing", display="implement",
                    obliges=["review"])
        self.data("plugin", "plans", "create", "Q", "--display", "Q", "--lib", "impl-thing")
        by_def = {s["def"]: s for s in self.data("plugin", "plans", "show", "p-1")["steps"]}
        self.assertEqual(by_def["impl-thing"]["deps"], [], "and not an edge onto the review")
        self.assertEqual(by_def["review"]["deps"], [by_def["impl-thing"]["id"]])

        # The other direction is untouched: an anchored step obliging an unanchored one
        # keeps the edge it always had, since the obliged end says nothing about when it
        # runs and the obligation is the only order there is.
        self.define("merge", name="merge the pull request", display="merge PR",
                    anchor="merge", obliges=["hand-check"])
        self.define("hand-check", name="what only a human can check", display="by hand")
        self.data(*_create("a job", "write it"))
        added = self.data("plugin", "plans", "name-step", "p-2", "merge")
        by_def = {s["def"]: s for s in added["steps"]}
        self.assertEqual(by_def["merge"]["deps"], [by_def["hand-check"]["id"]])
        self.assertEqual(by_def["hand-check"]["deps"], ["step-1"])

    def test_a_template_places_each_entry_against_the_ones_before_it(self):
        """A template got none of the anchor fix while every entry was expanded before any
        of them landed: `_place` saw an empty plan every time, so an anchored step found
        nothing to be placed against, was marked a deliberate root, and then had the
        entry's own `after` edge written onto it — a step claiming to be a start and
        carrying a wait, with the change approval back after the implementation, which is
        the precise defect anchors exist to remove.

        Each entry lands before the next is expanded now, and its `after` is drawn in the
        same round — an entry expanded while the one before it still had no edges saw two
        implementation steps that both looked like sinks and waited on both.
        """
        d = self.catalogue("templates")
        d.mkdir(parents=True, exist_ok=True)
        (d / "ship.json").write_text(json.dumps(
            {"title": "ship it", "display": "ship it", "steps": [
                {"name": "implement it", "display": "implement"},
                {"name": "test it", "display": "tests", "after": [1]},
                {"def": "create-pr", "after": [2]},
                {"def": "merge", "after": [3]}]}))
        made = self.data("plugin", "plans", "template", "use", "ship")
        at = {s["id"]: s for s in made["steps"]}
        by_def = {s["def"]: s for s in made["steps"] if s.get("def")}

        self.assertEqual(by_def["change-approval"]["deps"], [], "before the work, still")
        self.assertTrue(by_def["change-approval"]["root"])
        # The review waits on the implementation's SINK and not on both of its steps,
        # which is what drawing the entry's edges in the same round buys.
        self.assertEqual([at[d]["display"] for d in by_def["review"]["deps"]], ["tests"])
        self.assertEqual(set(by_def["create-pr"]["deps"]),
                         {by_def["review"]["id"], by_def["merge-human-review"]["id"],
                          by_def["change-approval"]["id"]})
        self.assertEqual([at[d]["display"]
                          for d in by_def["merge-human-review"]["deps"]], ["tests"])
        self.assertEqual(by_def["merge"]["deps"], [by_def["create-pr"]["id"]])
        self.assertNotIn("incomplete", made, f"and nothing is left to fix: {made}")

    def test_the_pr_waits_on_the_approval_it_obliged(self):
        """The guardrail the spec told this rework not to loosen: no PR without an approved
        change contract behind it. It was loosened, and this is the test that would have
        caught it.

        The anchor puts the approval at the very start, where nothing lower exists for it
        to come after — and a first draft left it there as a marked root that NO STEP IN THE
        PLAN LISTED. `obliged_by` is a label; only an edge is a wait. So the whole flagship
        plan could be ticked to merged past an approval nobody had done, with `validate`
        silent, and the tick chain never handed anybody the two-section contract that step
        is the whole reason for. The obligation goes back as an edge on the obliging step
        wherever the anchor left none.
        """
        made = self.data("plugin", "plans", "create", "flagship", "--display", "flag",
                         "--step", "impl = build it", "--lib", "create-pr", "--lib", "merge")
        by_def = {s["def"]: s for s in made["steps"] if s.get("def")}
        approval = by_def["change-approval"]["id"]
        self.assertIn(approval, by_def["create-pr"]["deps"], "no PR without the approval")
        self.assertEqual(by_def["change-approval"]["deps"], [], "and it is still the start")
        self.assertTrue(by_def["change-approval"]["root"])
        self.assertNotIn("incomplete", made)

        # And the tick chain does not hand over the PR while the approval is open, which is
        # how an agent following `next — this move unblocked` walked past it.
        self.ok("plugin", "plans", "tick", "step-1")
        released = json.loads(self.ok("plugin", "plans", "tick",
                                      by_def["review"]["id"], "--json"))
        self.assertEqual(released["data"].get("next", []), [],
                         "the review alone does not release the PR")
        after = json.loads(self.ok("plugin", "plans", "tick", approval, "--json"))
        self.assertEqual(after["data"].get("next", []), [],
                         "approval still does not release a PR with no human list")
        after = json.loads(self.ok("plugin", "plans", "tick",
                                   by_def["merge-human-review"]["id"], "--json"))
        self.assertEqual([s["def"] for s in after["data"]["next"]], ["create-pr"])

    def test_an_obligation_left_out_of_the_order_is_reported(self):
        """The door behind the edge, so that a future anchor cannot lose one in silence.

        An obliged step is added so it CANNOT be omitted, and one that nothing waits on and
        that comes after nothing is omitted in every way that counts — the plan reads as
        finished with it still open. Reported, never refused, like everything else in that
        door: the file is meant to be edited.

        The condition is the generator's own, from the other side, which is what keeps it
        from firing on the shapes the generator makes. An obliged step whose obliger runs
        EARLIER — `change-approval` obliges `review`, four bands ahead of it — is not
        reported, because an edge there would say the approval waits on the review, which
        is the inversion the anchor exists to remove.
        """
        self.data("plugin", "plans", "create", "D", "--display", "D",
                  "--step", "impl = build it", "--lib", "create-pr")
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

        # The PR stops waiting on the approval, which is the exact shape the bug produced.
        steps = {s["def"]: s["id"] for s in self.steps() if s.get("def")}
        self.edit_step(steps["create-pr"],
                       deps=[steps["review"], steps["merge-human-review"]])
        said = self.ok("plugin", "plans", "validate", "p-1")
        self.assertIn("left out of the order", said)
        self.assertIn(steps["change-approval"], said)

        # A skip with its reason is the sanctioned way past an obligation, so a skipped one
        # is not reported — it was dealt with rather than forgotten.
        self.ok("plugin", "plans", "skip", steps["change-approval"],
                "--why", "a one-line typo fix")
        self.assertNotIn("left out of the order",
                         self.ok("plugin", "plans", "validate", "p-1"))

    def test_create_lib_lands_a_resolved_library_step_in_the_one_call(self):
        """The whole plan in one command, which is the difference between `create` and
        `create` plus an unbounded number of follow-ups.

        A `--lib` step is a LINK like any other named step — `def` stored, `name` null,
        the text resolved out of the library at render — and it is placed by its anchor,
        so where the flag sat among the others decides nothing.
        """
        made = self.data("plugin", "plans", "create", "make X work",
                         "--display", "make X work end to end",
                         "--lib", "review", "--step", "impl = write it",
                         "--lib", "change-approval")
        by_def = {s.get("def"): s for s in made["steps"]}
        self.assertEqual(by_def["review"]["name"], "review the implementation")
        self.assertEqual(by_def["review"]["display"], "review")
        stored = {s["id"]: s for s in self._doc()["plans"][0]["steps"]}
        self.assertEqual(stored[by_def["review"]["id"]]["name"], None,
                         "stored as a link, not a copy")
        # Named last, and it still runs first; the review still comes after the work.
        self.assertTrue(by_def["change-approval"]["root"])
        self.assertEqual(by_def["review"]["deps"],
                         [by_def[None]["id"]])
        self.assertNotIn("incomplete", made, f"and it needs no fixing up: {made}")

        # A name the library does not have is refused, and nothing is written.
        code, out, _ = self.sb("plugin", "plans", "create", "another", "--display", "b",
                               "--lib", "nonesuch", "--json")
        self.assertEqual(code, 1)
        self.assertIn("no step definition 'nonesuch'", json.loads(out)["data"]["error"])
        self.assertEqual([p["id"] for p in self.data("plugin", "plans", "list")], ["p-1"])

    def test_create_lib_sorts_its_flags_so_the_order_they_are_typed_decides_nothing(self):
        """The claim `--lib` makes, and the one thing in this file that makes it true.

        `_place` looks BACKWARDS: a step is placed against the plan as it stands, so a
        merge minted before the PR exists waits on whatever the plan ended with then and is
        never re-deped. `create --lib` answers that by sorting what it was given by anchor
        before minting any of it — which is exactly why the same flags in either order have
        to produce the same graph. `name-step` takes several names and sorts them the same
        way, and the test below is the same claim made about that verb.

        Named in the REVERSE of the order they run, because that is the case the sort
        exists for: forwards, the anchors alone would get there.
        """
        back = self.data("plugin", "plans", "create", "B", "--display", "B",
                         "--step", "impl = build it", "--lib", "merge", "--lib", "create-pr")
        by_def = {s["def"]: s for s in back["steps"] if s.get("def")}
        self.assertIn(by_def["merge-human-review"]["id"], by_def["create-pr"]["deps"],
                      "the PR waits on the human list, whichever flag came first")
        self.assertEqual(by_def["merge"]["deps"], [by_def["create-pr"]["id"]])
        self.assertNotIn("incomplete", back)

        # And the same flags the other way round are the same plan, edge for edge.
        fwd = self.data("plugin", "plans", "create", "F", "--display", "F",
                        "--step", "impl = build it", "--lib", "create-pr", "--lib", "merge")
        shape = lambda p: [(s.get("def") or s["name"], s["deps"], s["root"])
                           for s in p["steps"]]
        self.assertEqual(shape(fwd), shape(back))

    def test_name_step_sorts_its_names_so_the_order_they_are_typed_decides_nothing(self):
        """The same claim `create --lib` makes, made about the verb that adds to a plan
        that already exists — and the fix for the ordering this file used to concede.

        `name-step` took ONE name, so `name-step p-1 merge` and then
        `name-step p-1 create-pr` left the merge waiting on the implementation: `_place`
        looks backwards, and when the merge was minted the PR did not exist. Taking
        several names and sorting them by anchor before minting any of them is what makes
        one call order-insensitive, so the merge waits on the PR whichever way round the
        names are typed.

        Named in the REVERSE of the order they run, because that is the case the sort
        exists for: forwards, the anchors alone would get there.
        """
        self.ok(*_create("a job", "build it"))
        back = self.data("plugin", "plans", "name-step", "p-1", "merge", "create-pr")
        by_def = {s["def"]: s for s in back["steps"] if s.get("def")}
        self.assertIn(by_def["merge-human-review"]["id"], by_def["create-pr"]["deps"],
                      "the PR waits on the human list, whichever name came first")
        self.assertEqual(by_def["merge"]["deps"], [by_def["create-pr"]["id"]])
        self.assertNotIn("incomplete", back)

        # And the same names the other way round are the same shape, edge for edge — read
        # off the whole plan, since the freetext step is what the PR is placed against.
        self.ok(*_create("a job", "build it"))
        self.data("plugin", "plans", "name-step", "p-2", "create-pr", "merge")
        shape = lambda pl: [(s.get("def") or s["name"], s["deps"], s.get("root"))
                            for s in self.steps(pl)]
        self.assertEqual(shape("p-2"), shape("p-1"))

    def test_name_step_still_places_each_call_against_the_plan_of_that_moment(self):
        """What sorting several names does NOT do: re-place what is already in the plan.

        One call sorts; two calls are two acts, and the second is placed against the plan
        as the first left it. That is `_place`'s rule and not a leftover — a lead who
        shaped an edge by hand would otherwise find it silently rewritten by a later
        `name-step`. So the answer to ordering is naming them together, and this pins that
        the answer stops there.
        """
        self.ok(*_create("a job", "build it"))
        self.data("plugin", "plans", "name-step", "p-1", "merge")
        impl = self.steps()[0]["id"]
        first = {s.get("def"): s for s in self.steps()}
        self.assertEqual(first["merge"]["deps"], [impl],
                         "the merge waits on the impl, which is all there was")

        self.data("plugin", "plans", "name-step", "p-1", "create-pr")
        by_def = {s.get("def"): s for s in self.steps()}
        self.assertIn(by_def["merge-human-review"]["id"], by_def["create-pr"]["deps"])
        self.assertNotIn(by_def["create-pr"]["id"], by_def["merge"]["deps"])

    def test_name_step_refuses_the_whole_call_before_it_writes_any_of_it(self):
        """A verb that writes once refuses once. A bad second name has to take the first
        one down with it: landing half of what was asked for and reporting a failure is
        the state nobody can read, since the plan then holds a step the caller was told
        about only as an error.
        """
        self.ok(*_create("a job", "build it"))
        code, out, _ = self.sb("plugin", "plans", "name-step", "p-1",
                               "create-pr", "nonesuch", "--json")
        self.assertEqual(code, 1)
        self.assertIn("no step definition 'nonesuch'", json.loads(out)["data"]["error"])
        self.assertEqual([s.get("def") for s in self.steps()], [None],
                         "and the good name landed nothing")

    def test_an_anchor_the_spine_does_not_have_is_refused_by_name(self):
        """A closed vocabulary, unlike `progress` and `gate`, and this is what that costs.

        The whole meaning of an anchor is its position in the order, so a word that is not
        in it has no position and there is nothing honest to do with one but refuse: a typo
        placed somewhere plausible-looking is the failure this file cannot have, since where
        a step runs is the thing anchors were added to get right. Refused when a definition
        carrying it is REACHED, like every other bad definition, so one typo takes down the
        commands that touch it and not every plan in the repo.
        """
        self.define("groundwork", name="do the groundwork", anchor="prr")
        self.ok(*_create("a job", "write it"))
        code, out, _ = self.sb("plugin", "plans", "name-step", "p-1", "groundwork", "--json")
        self.assertEqual(code, 1)
        why = json.loads(out)["data"]["error"]
        self.assertIn("not where anything runs", why)
        self.assertIn("design, build, review, pr, pre-merge, merge", why)
        self.assertEqual(len(self._doc()["plans"][0]["steps"]), 1, "and nothing was written")

        # A definition nothing reaches is not a definition anything refuses over.
        self.ok("plugin", "plans", "name-step", "p-1", "review")

    def test_placement_never_writes_a_marked_root_and_a_dep_onto_one_step(self):
        """The two say opposite things, and `_wrong` reports the pair on a hand-edit — so
        the generator writing one itself would be this file failing its own door.

        Reachable where an obliging step and the step it obliges share a band: both are
        placed with nothing lower than them, so both are marked starts, and then the
        obligation is put back as an edge onto the one that obliged. The mark comes off
        with the write, exactly as the removed `dep` verb took it off.
        """
        self.define("audit", name="audit the change", anchor="review", obliges=["sign-off"])
        self.define("sign-off", name="sign the audit off", anchor="review")
        made = self.data("plugin", "plans", "create", "A", "--display", "A", "--lib", "audit")
        by_def = {s["def"]: s for s in made["steps"]}

        self.assertEqual(by_def["audit"]["deps"], [by_def["sign-off"]["id"]],
                         "the obligation is an edge, since the anchors drew none")
        self.assertFalse(by_def["audit"]["root"], "and the start mark came off with it")
        self.assertTrue(by_def["sign-off"]["root"], "which is now the plan's real start")
        self.assertNotIn("incomplete", made, f"no door fires on what it made: {made}")
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

    # -- the optional plan review, wired by hand --------------------------------

    def test_plan_review_shares_the_approvals_band_and_nothing_brings_it(self):
        """The two halves of what `plan-review` IS, asserted on the shipped files.

        SAME BAND as `change-approval`, because a review of the plan runs before the plan
        is approved and both are design work — which is also why the edge between them is
        not drawn, and the test below is about that. And OPTIONAL in the strict sense:
        nothing in the shipped library composes it and nothing obliges it, so it reaches a
        plan only because somebody named it. That is the property the whole step rests on —
        an obligation would put a reviewer on every bounded job, which is the process this
        design exists to remove — and it is a property of the CATALOGUE rather than of any
        one definition, so it is read off all of them.
        """
        lib = {f.stem: json.loads(f.read_text())
               for f in self.catalogue("library").glob("*.json")}
        self.assertEqual(lib["plan-review"]["anchor"], lib["change-approval"]["anchor"])
        self.assertEqual(lib["plan-review"]["anchor"], "design")

        self.assertNotIn("obliges", lib["plan-review"], "it obliges nothing")
        self.assertNotIn("steps", lib["plan-review"], "and composes nothing")
        for key, spec in lib.items():
            self.assertNotIn("plan-review", spec.get("obliges") or [], key)
            self.assertNotIn("plan-review", spec.get("steps") or [], key)

        # So the landing shape nobody asked to review arrives without one.
        made = self.data("plugin", "plans", "create", "ship it", "--display", "ship it",
                         "--step", "impl = write it", "--lib", "create-pr", "--lib", "merge")
        self.assertNotIn("plan-review", [s.get("def") for s in made["steps"]])

    def test_the_hand_wired_plan_review_comes_before_the_approval_and_validates(self):
        """What a planner has to type, and that the graph it leaves is clean.

        `_place` looks at STRICTLY LOWER bands, so two `design` steps are both minted as
        marked starts with nothing between them: naming `plan-review` beside the approval
        does not order the two, and this asserts that first because it is the whole reason
        the wiring is manual. The planner then writes ONE edit — the review's id into
        `change-approval.deps`, and that step's `root` to false, since `_wrong` reports a
        step that carries a start mark and a dep — and what comes out is a plan where the
        approval waits on the review and `validate` finds nothing to say.
        """
        made = self.data("plugin", "plans", "create", "ship it", "--display", "ship it",
                         "--step", "impl = write it", "--lib", "plan-review",
                         "--lib", "create-pr", "--lib", "merge")
        by_def = {s["def"]: s for s in made["steps"] if s.get("def")}
        review, approval = by_def["plan-review"], by_def["change-approval"]
        self.assertEqual((review["deps"], review["root"]), ([], True))
        self.assertEqual((approval["deps"], approval["root"]), ([], True),
                         "the anchors draw no edge inside a band, so neither is ordered")

        self.edit_step(approval["id"], deps=[review["id"]], root=False)

        stored = {s.get("def"): s for s in self.steps()}
        self.assertEqual(stored["change-approval"]["deps"], [review["id"]],
                         "the approval now waits on the plan review")
        self.assertTrue(stored["plan-review"]["root"], "which is the plan's real start")
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

    def test_the_optional_plan_review_leaves_the_anchor_spine_alone(self):
        """Adding a definition in an existing band adds no band, and this pins that the
        way the spine is pinned everywhere else: the tuple, and the refusal that quotes it.

        The spine is what every anchored definition is ordered by, so a new one arriving
        with a band of its own would silently re-place every plan in the repo. `plan-review`
        reuses `design` precisely so it cannot, and the shape of a plan that never names it
        is unchanged — same steps, same edges, same marked root.
        """
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        self.assertEqual(_plans()._ANCHORS,
                         ("design", "build", "review", "pr", "pre-merge", "merge"))

        self.ok(*_create("a job", "write it"))
        code, out, _ = self.sb("plugin", "plans", "name-step", "p-1", "plan-review",
                               "--json")
        self.assertEqual(code, 0, out)
        self.define("groundwork", name="do the groundwork", anchor="plan-review")
        code, out, _ = self.sb("plugin", "plans", "name-step", "p-1", "groundwork", "--json")
        self.assertEqual(code, 1, "a definition's key is not a band")
        self.assertIn("design, build, review, pr, pre-merge, merge",
                      json.loads(out)["data"]["error"])

        # And the shipped landing shape, which names no plan review, is the graph it was.
        made = self.data("plugin", "plans", "create", "B", "--display", "B",
                         "--step", "impl = build it", "--lib", "create-pr", "--lib", "merge")
        by_def = {s["def"]: s for s in made["steps"] if s.get("def")}
        impl = next(s for s in made["steps"] if not s.get("def"))
        self.assertTrue(by_def["change-approval"]["root"])
        self.assertEqual(by_def["review"]["deps"], [impl["id"]])
        self.assertEqual(sorted(by_def["create-pr"]["deps"]),
                         sorted([by_def["review"]["id"],
                                 by_def["merge-human-review"]["id"],
                                 by_def["change-approval"]["id"]]))

    def test_create_lib_refuses_before_it_writes_anything(self):
        """The guards on the new flag, which are the ones `name-step` already had.

        Both are refusals rather than exceptions and both happen BEFORE the plan is made:
        a `create` that wrote a plan and then failed would leave the agent retrying and the
        store holding two. A definition with no board label cannot be named at all — the
        label lives in the definition and there is no argument here that could supply one —
        and a catalogue file that will not parse is the catalogue's answer, said so a
        machine reader hears it rather than raised as a traceback.
        """
        self.define("groundwork", name="do the groundwork", display=None)
        code, out, _ = self.sb("plugin", "plans", "create", "a job", "--display", "d",
                               "--lib", "groundwork", "--json")
        self.assertEqual(code, 1)
        self.assertIn("library/groundwork.json", json.loads(out)["data"]["error"])
        self.assertEqual(self._doc()["plans"], [], "and no plan was made")

        (self.catalogue("library") / "broken.json").write_text("{nope")
        code, out, _ = self.sb("plugin", "plans", "create", "a job", "--display", "d",
                               "--lib", "review", "--json")
        self.assertEqual(code, 1)
        self.assertIn("not readable JSON", json.loads(out)["data"]["error"])
        self.assertEqual(self._doc()["plans"], [])
        (self.catalogue("library") / "broken.json").unlink()

        # And a definition that PARSES and is still unusable — the expansion is where that
        # is met, inside the mint, under the lock, with the plan half built. It comes back
        # as a refusal like the two above and not as a raised exception, because a `create`
        # that failed after writing would leave the agent retrying and the store with two.
        self.define("groundwork", name="do the groundwork", anchor="prr")
        code, out, _ = self.sb("plugin", "plans", "create", "a job", "--display", "d",
                               "--lib", "groundwork", "--json")
        self.assertEqual(code, 1)
        self.assertIn("not where anything runs", json.loads(out)["data"]["error"])
        self.assertEqual(self._doc()["plans"], [])

    def test_an_unanchored_lib_step_hangs_off_what_the_plan_ends_with(self):
        """`create --lib` places what it mints against the freetext steps typed beside it,
        which is what makes one command a whole plan rather than a plan and a loose step.

        Said with an UNANCHORED definition on purpose: an anchored one would be placed by
        its band whatever it was handed, so this is the case that proves the plan's own tail
        is what a `--lib` step is minted against."""
        self.define("scan", name="scan the code", display="scan")
        made = self.data("plugin", "plans", "create", "S", "--display", "S",
                         "--step", "one = do the first", "--step", "two = do the second",
                         "--lib", "scan")
        by_def = {s.get("def"): s for s in made["steps"]}
        self.assertEqual(by_def["scan"]["deps"], ["step-2"], "the tail, not the whole plan")
        self.assertNotIn("incomplete", made)

    def test_a_tick_prints_the_instructions_for_what_it_unblocked(self):
        """The moment a step is picked up is the moment its `about` is worth printing, and
        it was the moment nothing marked. `_resolve` merges a definition's name, display
        and command onto a step and deliberately not its prose — a page under every row
        would bury the plan — so an agent met the step and never the instruction unless it
        already knew to go and read the definition, which is a thing you learn by having
        got it wrong."""
        self.data(*_create("a job", "write it"))
        self.data("plugin", "plans", "name-step", "p-1", "review")
        out = json.loads(self.ok("plugin", "plans", "tick", "s-1", "--json"))
        said = " ".join(self.ok("plugin", "plans", "tick", "s-1").split())

        self.assertEqual([s["def"] for s in out["data"]["next"]], ["review"])
        self.assertIn("read the approved text out of that step's `output`",
                      out["data"]["next"][0]["about"])
        self.assertIn("next — this move unblocked:", said)
        self.assertIn("The review you would run anyway", said)

        # And the same view asked for on purpose, for a step nothing has just released.
        one = self.ok("plugin", "plans", "show", "step-2")
        self.assertIn("The review you would run anyway", " ".join(one.split()))


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

    def _step(self, sid: str) -> dict:
        """One step, read back out of the file rather than out of a verb's own answer."""
        return next(s for p in self._doc()["plans"] for s in p["steps"] if s["id"] == sid)

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
        code, out, _ = self.sb("plugin", "plans", "create", "another", "--display", "b",
                               "--step", "review it", "--json")
        self.assertEqual(code, 1)
        self.assertIn("list claims", json.loads(out)["data"]["error"])
        self.assertEqual(len(self._doc()["plans"]), 1, "and nothing was written")

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
        not a chain is reshaped in the file, which is where a plan is shaped.
        """
        made = self.data(*_create("a job", "write it", "review it", "merge it"))
        self.assertEqual([s["deps"] for s in made["steps"]], [[], ["step-1"], ["step-2"]])
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
        self.assertIn('"deps": ["<step>"]', said, "and it says the edit that fixes it")
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
                     ("note", "s-2", "--text", "a note"),
                     ("skip", "s-2", "--why", "not needed")):
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

    def test_show_header_falls_back_to_display_when_title_is_absent(self):
        """Records may intentionally have only the required board name. `show`, `list`,
        and the board all use that display before declaring the record untitled."""
        self.data("plugin", "plans", "record", "--display", "repair workspace labels")
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertEqual(shown.splitlines()[0], "p-1  repair workspace labels")
        self.assertIn("repair workspace labels", self.ok("plugin", "plans", "list"))

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
        self.assertEqual(review["deps"], ["step-2"], "the review comes after the work")
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

    def test_a_deliberate_second_root_is_marked_and_then_it_is_complete(self):
        """The answer to a plan with two real starts, which used to be a false edge.

        Two steps on disjoint work, starting side by side, could only clear the warning by
        recording an order that never happened — a lie in the record to satisfy a rendering
        rule. `root: true` says the start is meant, and a start that says so is no more
        incomplete than the plan's first one is.
        """
        self.ok(*_create("a job", "build it", "document it"))
        self.edit_step("s-2", deps=[])
        self.assertIn("no dep: step-2", self.ok("plugin", "plans", "validate", "p-1"))

        self.edit_step("s-2", root=True)
        self.assertTrue(self._step("step-2")["root"])
        self.assertEqual(self._step("step-2")["deps"], [], "and no edge was invented")
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))
        self.assertIn("parallel start", self.ok("plugin", "plans", "show", "p-1"),
                      "and `show` says which starts were authored as starts")

        # AND THE MARK AND AN EDGE CANNOT BOTH STAND, which is what the verb that wrote an
        # edge used to enforce by clearing the mark. The rule outlives the verb: a step
        # claiming to be a start and carrying a wait draws as a start on the board and as a
        # wait in the file, and only one of those can be true.
        self.edit_step("s-2", deps=["step-1"])
        said = self.ok("plugin", "plans", "validate", "p-1")
        self.assertIn("marked a deliberate root and given a dep", said)
        self.assertIn("step-2", said)

    def test_an_unmarked_second_root_is_still_reported_and_the_fix_names_both_ways(self):
        """The marker is the whole of what separates the two cases, so the unmarked one is
        reported exactly as before — a bare `deps: []` is a forgotten edge and a parallel
        start in the same bytes. What changed is that the warning now offers an answer that
        is not an edge nobody means."""
        self.ok(*_create("a job", "build it", "document it"))
        self.edit_step("s-2", deps=[])
        said = self.ok("plugin", "plans", "validate", "p-1")
        self.assertIn('"deps": ["<step>"]', said)
        self.assertIn('"root": true', said)

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
                         [[], ["step-1"], ["step-1"], ["step-2", "step-3"]])
        self.assertNotIn("incomplete", made)

    def test_a_template_carries_its_own_display_names_and_the_order_between_its_steps(self):
        """The shipped `docs` template, used, which is the one plan a lead gets for free.

        What it has to land is a chain: every step with a board label, every step but the
        first with a dep, and its obliged human review before the PR that presents it. A
        template that landed a loose stack would be the design's own example of the shape
        it says a plan must not have.
        """
        made = self.data("plugin", "plans", "template", "use", "docs")
        self.assertTrue(made["display"], "the copy has a board name of its own")
        self.assertEqual([s["deps"] for s in made["steps"]][0], [])
        self.assertTrue(all(s["deps"] or s.get("root") for s in made["steps"][1:]),
                        f"every later step is chained or a deliberate root: "
                        f"{[s['deps'] for s in made['steps']]}")
        self.assertNotIn("incomplete", made)
        # The PR waits for the list and the merge waits for the PR: the list exists in the
        # first comment the human reads.
        merge = next(s for s in made["steps"] if s.get("def") == "merge")
        review = next(s for s in made["steps"] if s.get("def") == "merge-human-review")
        pr = next(s for s in made["steps"] if s.get("def") == "create-pr")
        self.assertIn(review["id"], pr["deps"])
        self.assertIn(pr["id"], merge["deps"])


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
        self.assertIn("step-1", lines)
        self.assertIn("step-2", lines)

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
        return next(s for pl in self._doc()["plans"] for s in pl["steps"]
                    if _same_id(s, sid))

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

    # -- a field this plugin has never heard of ---------------------------------

    def test_an_invented_field_shows_in_the_terminal_and_not_only_in_the_dumps(self):
        """The module docstring says a step carrying a field this file has never heard of
        is a feature and not corruption. `--json` and `--markdown` kept that promise —
        neither knows a schema — and `show` did not: it is a hand-written template that
        draws every field by name, so an invented one was silently invisible in the one
        view a lead actually reads. Now the leftovers are drawn on a line of their own.

        Only the leftovers, which is the half worth pinning: every field the template
        already draws by name must not appear a second time as an unknown, `output`
        rendered as `out` and a definition's resolved `command` included."""
        self.plan("write it")
        self.edit_step("s-1", risk="the migration is one-way",
                       reviewed_by="andrew", output="what the step produced")

        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("risk  the migration is one-way", shown)
        # A key wider than the label column still gets its two spaces: the key is the
        # label here, and one that ran into its own value would be unreadable.
        self.assertIn("reviewed_by  andrew", shown)
        self.assertIn("out   what the step produced", shown)
        # Drawn once each. `output` has its own line above, so it is not a leftover, and
        # neither is the owner status this rendering reads live and stores nowhere.
        self.assertEqual(shown.count("what the step produced"), 1)
        self.assertNotIn("output", shown)
        self.assertNotIn("owner_status", shown)
        # And it was already in the schema-blind renderings, which is what made the
        # terminal the odd one out.
        self.assertIn("the migration is one-way",
                      self.ok("plugin", "plans", "show", "p-1", "--markdown"))

        # A collection is left to `--json`: there is no place under a step line for one,
        # and this door falls back rather than raising on whatever a hand-edit put there.
        self.edit_step("s-1", attempts=["monday", "tuesday"])
        self.assertNotIn("monday", self.ok("plugin", "plans", "show", "p-1"))
        self.assertIn("monday", json.dumps(self.data("plugin", "plans", "show", "p-1")))

    def test_an_invented_field_cannot_forge_a_row_any_more_than_a_gate_can(self):
        """The rule the new line has to obey to be allowed to exist. Every value drawn in
        this plugin goes through `_flat`, and a field nobody here has heard of is the last
        place that could have been forgotten — it is the one whose NAME is a hand-edit
        too, so both halves of the line are escaped."""
        self.plan("write it")
        self.edit_step("s-1", risk="fine\ns-9   done      merged")

        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("\\ns-9", shown)
        self.assertFalse([ln for ln in shown.splitlines() if ln.startswith("s-9")])


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
        instant, mark a healthy job abandoned for the rest of its life. Until a later read
        repairs `workspace_from`, the worktree question is asked
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
        command in the repo queued behind it.

        A REAL FORK of a real wedged program, which is the only way this can be true: the
        thing under test is the timeout on the subprocess, so there is nothing here to
        stand in for it. The stub in `PlansSandbox` leaves it alone of its own accord —
        the wedged `sb` is not this repo's build — and this says so out loud.
        """
        self.real_sb_subprocess()
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
            return self.sb("delegate", *argv, "--name", "a thing")

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


class PlannerPackageTest(PlansSandbox):
    """The plan writer's three reads and the field that says a plan has one.

    A plan writer is the first-class role this plugin contributes plus what else it owns:
    `planner`, the instruction it reads on its first turn; `catalog`, the vocabulary it may name; and the plan-level
    `planner` field, which moves the shape of one plan off the worktree's owner and onto
    the agent that wrote it. The properties worth pinning are that the catalogue is
    GENERATED — it says what this repo has, not what someone once wrote down — that it
    survives one broken file in it, and that the capability vocabulary in it is the same
    vocabulary `sb grant` accepts rather than a second list that will drift.

    Unproven here, and not provable at this level: that a real planner reads any of this,
    plans proportionally, or invents no names. That is the workflow question the whole
    design rests on, and Unit 5's development evaluation is where it is answered.
    """

    def catalog(self) -> dict:
        return self.data("plugin", "plans", "catalog")

    def test_the_planner_instruction_is_printed_and_carries_no_editor_notes(self):
        """What the planner reads on its first turn: what it is, what it does not do, and
        the two commands it goes on to run. Asserted on the printed text rather than on the
        file, because the file has a maintainer's comment block at the top that a planner
        must never be handed — `sb presets <name>` drops one the same way."""
        out = self.ok("plugin", "plans", "planner")
        for expected in ("You are the plan writer for one job.",
                         "sb plugin plans catalog",
                         "sb plugin plans guide",
                         "THIS REPLACES THE FINDINGS NOTE",
                         "STRATEGY IS ADVISORY AND NEVER ENFORCEMENT"):
            self.assertIn(expected, " ".join(out.split()))
        self.assertNotIn("<!--", out)
        self.assertEqual(json.loads(self.ok("plugin", "plans", "planner", "--json"))
                         ["data"]["planner"].strip(), out.strip())
        # Reads one file and writes nothing: no state file exists after it runs.
        self.assertEqual(self._files(), [])

    def test_the_planner_instruction_bounds_its_ownership_and_hands_the_shape_back(self):
        """The 2026-08-27 ownership model, on the planner's side of it. The planner is a
        BOUNDED specialist: it expands the plan the task owner already made, challenges the
        approach, clears the `planner` field and finishes. Everything that made it long-lived
        — creating its own plan, a fresh main it hands execution to, staying open for the
        plan's life, the completion handshake and the dead-planner fallback ladder — is gone,
        because all of it existed to support a planner that outlives its plan.

        Asserted on the printed text as one whitespace-joined run, like the guide tests: the
        claims are what matter, not where a reflow puts the line breaks."""
        said = " ".join(self.ok("plugin", "plans", "planner").split())
        for expected in (
                # Bounded: the shape is held, not owned, and writing the plan buys no claim
                # on running it.
                "You do not own the job",
                "gives you no claim on running it",
                # The plan is not the planner's to create: it exists first, and is expanded.
                "THE PLAN IS ALREADY THERE",
                "You EXPAND that plan in place. Do not create a second one",
                # Challenge is half the job, and over-delegation is the named target.
                "CHALLENGE IT",
                "Delegation is the one to look at hardest",
                # The clean return, in the three acts that make it observable.
                "Clear the `planner` field",
                "Approval is the task owner's to obtain, not yours",
                "You are finished; you do not stay open",
                # The one structural rule the old sibling apparatus was protecting.
                "you do not spawn the agent that runs the plan"):
            self.assertIn(expected, said)
        # The long-lived model is gone, not reworded: no handshake, no fallback ladder, no
        # sibling topology, and no instruction to stay open on a background wait.
        for retired in ("You do NOT spawn the main agent.",
                        "the handoff has two halves",
                        "`sb waiting` IS WHAT KEEPS YOU CLEANLY OPEN",
                        "sends you a delta — BY YOUR NAME",
                        "RE-CHECK THE TREE",
                        "`sb restore` IS DELIBERATELY NOT ON THIS PATH"):
            self.assertNotIn(retired, said)

    def test_the_catalogue_is_generated_from_this_repo_and_not_from_a_list(self):
        """Every category, keyed, and each one holding what this sandbox actually has —
        including a role and a template written into it by this test, which a hardcoded
        inventory could not know about."""
        (self.defaults / "roles" / "archivist.md").write_text(
            '+++\nmodel = "cheap"\ncapabilities = ["spawn"]\n+++\nYou file things.\n')
        self.define("triage", name="work out what is wrong", anchor="design")

        got = self.catalog()
        self.assertEqual(sorted(got), ["capabilities", "library", "models", "plugins",
                                       "presets", "problems", "roles", "templates"])
        self.assertEqual(got["problems"], [])
        roles = {r["name"]: r for r in got["roles"]}
        self.assertEqual(roles["archivist"]["model"], "cheap")
        self.assertEqual(roles["archivist"]["capabilities"], ["spawn"])
        self.assertIn("researcher", roles)
        self.assertIn("strong", [t["name"] for t in got["models"]["tiers"]])
        self.assertIn("design-gate", got["presets"]["available"])
        self.assertIn("plans", got["plugins"])
        self.assertIn("triage", [d["name"] for d in got["library"]])
        self.assertIn("change-approval", [d["name"] for d in got["library"]])
        # The human digest is a digest and says where the detail is read.
        shown = " ".join(self.ok("plugin", "plans", "catalog").split())
        self.assertIn("sb plugin plans library <name>", shown)
        self.assertIn("Skills and tools are NOT here", shown)

    def test_the_catalogues_capabilities_are_the_vocabulary_grant_accepts(self):
        """One vocabulary, not two. The plugin assembles this list itself — it holds no
        broker — so the pin is equality against a real one.

        BOTH REPO-MINTED SOURCES ARE IN THE FIXTURE, because equality against the shipped
        four would hold for a list somebody typed out once and would prove nothing: a
        capability this repo declared at a side-effect boundary (`deploy`), and one named
        only by a role template (`release`). Those are the two branches
        `known_capabilities` unions in beyond the constant, and a catalogue missing either
        would advertise a different set from the one `sb grant` accepts — the second of
        them being the whole reason a role file can mint vocabulary at all."""
        (self.sw / "settings.toml").write_text(
            f'[paths]\nuser_state = "{self.user_state}"\n\n'
            f'[capabilities.side_effects]\ndeploy = ["merge"]\n')
        (self.defaults / "roles" / "releaser.md").write_text(
            '+++\nmodel = "cheap"\ncapabilities = ["release"]\n+++\nYou cut releases.\n')
        db = store.connect(self.repo)
        broker = cli.Broker(db, FakeHerdr(self.repo / "worktrees"), repo=self.repo)
        try:
            self.assertEqual(self.catalog()["capabilities"],
                             sorted(broker.known_capabilities()))
            # Named rather than inferred from the equality above: a bug that dropped BOTH
            # branches from both sides would still be equal, and equal to the wrong thing.
            self.assertIn("deploy", broker.known_capabilities())
            self.assertIn("release", broker.known_capabilities())
        finally:
            db.close()
        got = self.catalog()["capabilities"]
        self.assertIn("deploy", got)
        self.assertIn("release", got)
        # And the role that minted it says the same thing in the other section, which is
        # what a planner reads before it recommends the grant.
        self.assertEqual([r["capabilities"] for r in self.catalog()["roles"]
                          if r["name"] == "releaser"], [["release"]])

    def test_one_broken_definition_costs_its_own_category_and_nothing_else(self):
        """A catalogue is the last thing that should stop being generated because one JSON
        file has a comma in the wrong place: the planner gets the other six categories and
        a line naming the file to fix."""
        d = self.catalogue("library")
        d.mkdir(parents=True, exist_ok=True)
        (d / "wrecked.json").write_text("{not json")

        code, out, _ = self.sb("plugin", "plans", "catalog")
        self.assertEqual(code, 0)
        got = self.catalog()
        self.assertEqual(got["library"], [])
        self.assertEqual(len(got["problems"]), 1)
        self.assertIn("the step library could not be read", got["problems"][0])
        self.assertIn("wrecked.json", got["problems"][0])
        self.assertIn("wrecked.json", out)
        # The categories that had nothing to do with that file are all still there.
        self.assertTrue(got["roles"] and got["capabilities"] and got["templates"])

    def test_a_planner_creating_a_plan_records_itself_as_its_shape_writer(self):
        """`--planner` is a claim the caller makes about itself, so what lands in the field
        is the calling agent — in the file, in the changelog, and on the rendered plan."""
        self.as_agent("researcher-plan-writer")
        self.ok(*_create("ship the thing", "impl write it"), "--planner")

        plan = self._doc()["plans"][0]
        self.assertEqual(plan["planner"], "researcher-plan-writer")
        self.assertIn("planner-managed by researcher-plan-writer",
                      self.ok("plugin", "plans", "changelog", "p-1"))
        self.assertIn("planner     researcher-plan-writer",
                      self.ok("plugin", "plans", "show", "p-1"))
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

    def test_a_plan_made_without_the_flag_carries_no_planner_at_all(self):
        """Absent, not null: the worktree-owner rule is what every ordinary plan keeps, and
        a field on every plan in the repo saying it has no plan writer is noise."""
        self.as_agent("lead-one")
        self.ok(*_create("ship the thing", "impl write it"))
        self.assertNotIn("planner", self._doc()["plans"][0])
        self.assertNotIn("planner", self.ok("plugin", "plans", "show", "p-1"))

    def test_a_human_cannot_claim_to_be_a_plans_planner(self):
        """The field names the agent a later delta and a later approval go back to, and
        there is no such agent when a person is typing. Refused, with the one field to
        write by hand instead — and nothing is created."""
        code, _, err = self.sb(*_create("ship the thing"), "--planner")
        self.assertNotEqual(code, 0)
        self.assertIn("resolved this caller to a human", err)
        self.assertEqual(self._files(), [])

    def test_the_guide_says_who_writes_a_planner_managed_plan_and_what_strategy_is(self):
        """The two claims Unit 2 reconciled, asserted on the printed guide. The first is
        the ownership move — a plan with a planner has one shape writer and it is not the
        worktree's owner. The second is the delta Unit 1 left: `strategy` IS schema-checked,
        every other field is not, and neither fact makes it enforcement."""
        said = " ".join(self.ok("plugin", "plans", "guide").split())
        for expected in (
                # Ownership, both halves: the planner where there is one, the worktree's
                # owner where there is not.
                "The worktree's owner: the lead, or the sole worker where there is no lead",
                "UNLESS THE PLAN NAMES A PLANNER",
                # Held, not owned: the field is a temporary handover with two named halves,
                # each written by whoever is giving something up.
                "moves it temporarily",
                "THE FIELD IS THE HANDOVER",
                "it clears the field, with a `note` saying so, when it hands the shape back",
                "A plan with no `planner` is the ordinary case",
                "sb plugin plans planner",
                "sb plugin plans catalog",
                # The strategy field: shaped, checked, and still only advice.
                "`strategy.schema.json` is the contract",
                "it is ADVISORY: nothing reads a strategy and acts on it",
                "Apart from `strategy` above there is no schema to satisfy"):
            self.assertIn(expected, said)

    def test_the_strategy_schema_verb_prints_the_shipped_contract(self):
        """The read path the guide's prose now names. What matters is that it prints the
        FILE the validator loads rather than a copy written out beside it: a second
        transcription of the schema would be the drift this verb exists to remove."""
        shipped = json.loads((Path(__file__).resolve().parent.parent / "defaults"
                              / "plugins" / "plans" / "strategy.schema.json")
                             .read_text(encoding="utf-8"))
        self.assertEqual(json.loads(self.ok("plugin", "plans", "strategy-schema")), shipped)
        self.assertEqual(self.data("plugin", "plans", "strategy-schema")["strategy_schema"],
                         shipped)

    def test_the_guide_names_every_strategy_field_the_schema_has(self):
        """The prose half, pinned to the schema rather than to itself. A plan writer reads
        the guide and not the JSON, so a field added to `strategy.schema.json` and not to
        the guide's bullet is a name nobody planning will ever see — and the two types that
        read like numbers and are not are what cost the p-25 worker a validate round."""
        said = " ".join(self.ok("plugin", "plans", "guide").split())
        schema = self.data("plugin", "plans", "strategy-schema")["strategy_schema"]
        names = list(schema["properties"])
        for parent in ("resources", "budget"):
            names += list(schema["properties"][parent]["properties"])
        for name in names:
            self.assertIn(f"`{name}`", said, f"the guide never names strategy.{name}")
        self.assertIn("`budget` holds `context` and `passes`, BOTH STRINGS", said)

    def test_the_planner_instruction_sends_a_plan_writer_at_the_types_first(self):
        """planner.md's own half: the strategy section points at both readings of the
        contract BEFORE the first strategy is written, rather than leaving `validate` to
        report it afterwards."""
        said = " ".join(self.ok("plugin", "plans", "planner").split())
        self.assertIn("sb plugin plans strategy-schema", said)
        self.assertIn("Both are STRINGS", said)

    def test_the_guide_carries_the_planner_seed_and_who_runs_the_plan_after(self):
        """The planner lifecycle at the TASK OWNER's altitude — the side read by whoever
        spawns one. Three things the guide has to get right: the capability seed (held
        `spawn`, `fork` when foreseen, and NEVER `write-tracked`), that seeding is two verbs
        and not a flag on one, and who runs the plan once the shape comes back — which since
        2026-08-27 is the task owner by default, with a fresh main an option that has to earn
        itself and that the owner spawns itself.

        Matched against the printed block as one whitespace-joined run, like the guide tests
        above: the claims are what is pinned, not the line breaks."""
        said = " ".join(self.ok("plugin", "plans", "guide").split())
        for expected in (
                "SPAWNING A PLANNER, AND WHO RUNS THE PLAN AFTERWARDS",
                # The plan is not created by the planner.
                "THE PLAN EXISTS BEFORE THE PLANNER DOES",
                # The seed, and the one grant it must never carry.
                "NEVER `write-tracked`",
                # Seeding is two verbs; there is no combined flag.
                "There is no `delegate --grant`",
                "`sb grant <agent> <cap>` adds anything beyond that template",
                # The clean return, and continuing as the default afterwards.
                "IT HANDS THE SHAPE BACK AND FINISHES",
                "CONTINUING IS THE DEFAULT",
                "A fresh main agent is an option that has to earn itself",
                # The one structural rule the retired sibling topology was protecting.
                "a fresh main is your child and never the planner's"):
            self.assertIn(expected, said)
        # The long-lived planner is gone from this side too.
        for retired in ("spawns BOTH the planner and the main agent",
                        "THE HANDOFF HAS TWO HALVES",
                        "Material deltas go to the planner BY NAME",
                        "route the candidate to `parent`",
                        "`sb restore` is NOT on this path"):
            self.assertNotIn(retired, said)

    def test_the_guide_names_every_library_root_and_the_library_still_agrees(self):
        """Bug 2026-08-26-143005 defect 1: a singular heading over a library with more than
        one unobliged root. Naming `create-pr` alone dropped the merge landing step, and the
        plan was well-formed, so nothing downstream could tell that truncation
        from a job that genuinely ended at the PR.

        The roots are DERIVED from the shipped library here rather than typed, because the
        guide now names them and a named list is a list that can go stale: add a definition
        nothing obliges, or make one of these three obliged by another, and this fails
        instead of the guide quietly becoming wrong again."""
        lib = json.loads(self.ok("plugin", "plans", "library", "--json"))["data"]
        obliged = {name for d in lib.values() for name in (d.get("obliges") or ())}
        roots = sorted(set(lib) - obliged)
        self.assertEqual(roots, ["create-pr", "implementation", "merge", "plan-review"])

        said = " ".join(self.ok("plugin", "plans", "guide").split())
        # The heading is plural, and the roots are named at the moment of composing.
        self.assertIn("NAME EVERY OUTERMOST STEP", said)
        self.assertIn("the library has FOUR steps nothing else brings", said)
        for root in roots:
            self.assertIn(f"`{root}`", said)
        # And the silence is named: a truncated plan is a legal plan.
        self.assertIn("naming one never brings another", said)

    def test_the_pr_comment_reads_as_a_live_render_rather_than_something_that_waits(self):
        """Bug 2026-08-26-143005 defect 2. `change-approval` says the approved text goes in
        `output` "because that is what the PR comment dumps" — true, causal, and one clause
        from "and only then tick", which is a real ordering constraint. Read temporally it
        says the comment waits for the approval, and an agent opened a PR carrying no plan.

        Both halves are pinned. `create-pr` has to say the comment renders the plan as it
        stands and is re-run at merge; `change-approval` has to KEEP its sentence, since it
        is the only thing saying why `output` must hold the full text. Deleting that sentence
        would pass a test that only checked the first half."""
        lib = json.loads(self.ok("plugin", "plans", "library", "--json"))["data"]

        pr = " ".join(lib["create-pr"]["about"].split())
        self.assertIn("renders the plan AS IT STANDS AT THAT MOMENT", pr)
        self.assertIn("waits for nothing: no step has to be finished first", pr)
        self.assertIn("`merge` does this same marked upsert again as it lands", pr)
        self.assertIn("never that the comment waits for it", pr)

        approval = " ".join(lib["change-approval"]["about"].split())
        self.assertIn("because that is what the PR comment dumps", approval)


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
        return next(s for p in self._doc()["plans"] for s in p["steps"]
                    if _same_id(s, sid))

    def test_a_gate_is_an_exit_condition_on_a_step_and_never_a_step_of_its_own(self):
        """The design's first rule about gates, and the one thing here not to get wrong. A
        design step ending in "no implementation until he confirms" needs no second step for
        the confirmation, so marking one adds nothing to the plan: the same two steps, one
        of them now carrying the sentence saying what he has to answer."""
        self.plan("shape the work", "merge it")
        self.edit_step("s-1", gate="he confirms the behavioural contract")

        self.assertEqual([s["id"] for s in self._doc()["plans"][0]["steps"]],
                         ["step-1", "step-2"])
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
        self.assertIn("step-1", said)

        self.edit_step("s-1", why="a one-line typo fix")
        self.assertEqual(self.step("s-1")["progress"], "skipped")
        self.assertEqual(self.step("s-1")["gate"], "he confirms the contract")
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("a one-line typo fix", shown)
        self.assertIn("he confirms the contract", shown)
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

        # Read off the registry rather than off this file's memory of it: a verb that wrote
        # or cleared a gate would have to break this test to arrive. `skip` IS a verb — it
        # moves progress, which is the thing a gate does not — and it leaves the gate where
        # it is, so a skipped gate is still on the board with its reason beside it.
        self.assertNotIn("gate", _plans_commands())
        self.ok("plugin", "plans", "tick", "s-1")
        self.ok("plugin", "plans", "skip", "s-1", "--why", "a one-line typo fix")
        self.assertEqual(self.step("s-1")["gate"], "he confirms the contract")

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
        self.assertIn("step-1", said)
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
        that stops `--with design-gate`, and nothing asserting there is.

        The preset is now the FORMAT and not one gate's sections — `change-approval` and
        `merge-human-review` both name it and head their messages differently — so what is
        pinned about the sections is that the file says they are the step's to name, and
        that the worked example still carries the two it was written around."""
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
        # The sections belong to the step, and the file says so where the agent will read
        # it. Pinned because the whole re-section is this sentence: without it the example
        # below reads as two headings to copy, which is what it stopped being.
        self.assertIn("WHICH ones is the step's own to say", body)
        # And the count is the step's too: the approval gate has two, the human-check list
        # has one, and a file insisting on two contradicted the step that
        # sends it the second reader.
        self.assertIn("merge-human-review", body)
        self.assertIn("Scope & Objectives", body)
        # And the worked example keeps the two it was written around, as an example.
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
                # What hand-editing can silently lose — and what it is NOT asked to do,
                # which is maintain the changelog: nothing validates or refuses on it.
                "NEVER drop or rewrite a changelog entry",
                "You do not have to ADD an entry for a hand-edit",
                "ADD A LIBRARY STEP with `create --lib` or `name-step`, not by hand",
                # And what naming one brings that typing a `def` does not: the chain of
                # obligations. A `def` written by hand resolves everything else itself.
                "what it does NOT do is materialise the steps its definition obliges",
                # The agent's real tools, named, where `$EDITOR` used to be — the line
                # that sent agents round the houses through a shell one-liner.
                "READ IT AND EDIT IT WITH YOUR NORMAL FILE TOOLS",
                "There is no editor to open and nothing to script",
                # `show --json` is a VIEW, and what it resolves must not go back in.
                "must never be written back into the file",
                # How a step is addressed, now that step numbers are per plan and a bare
                # one can be ambiguous. The qualified form is what a refusal asks for.
                "HOW A STEP IS ADDRESSED",
                "`p-16/step-3` names the plan on the front",
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
        for expected in ("plan-2", "render the plan", "step-2", "write the renderer",
                         "waits on review", "the diff is in"):
            self.assertIn(expected, md)
        # The other plan is in the same store and none of it is here.
        # `plan-1` and not `p-1`: ids render long here, and `step-1` ENDS in `p-1`, so the
        # short spelling would find itself inside this plan's own steps and pass for the
        # wrong reason.
        for gone in ("plan-1", "the other job", "a step nobody wants"):
            self.assertNotIn(gone, md)
        # And `--json` is what it always was: the plan record, untouched by the flag.
        self.assertEqual(self.data("plugin", "plans", "show", "p-2", "--markdown")["id"],
                         self.data("plugin", "plans", "show", "p-2")["id"])
        self.assertEqual(self.data("plugin", "plans", "show", "p-2", "--markdown"),
                         self.data("plugin", "plans", "show", "p-2"))

    def test_the_anchor_stays_out_of_the_comment_a_human_reads(self):
        """The one field resolved onto the view for the CODE and for no reader.

        `show --markdown` is what `create-pr` posts onto the pull request, so a step's
        resolved `name`, `display` and `command` belong in it — they are what whoever turns
        up reads. `anchor` is not: it is how this file decided where to put the step, weeks
        earlier, and `anchor: pr` under a step means nothing to that reader. Dropped from
        the copy that is dumped rather than skipped by the renderer, because a renderer
        that knew one field name would be the template this one exists not to be.

        `--json` still carries it, and that half is the point of the split: the machine
        reader is who the field is for.
        """
        self.ok(*_create("ship it", "write it"))
        self.ok("plugin", "plans", "name-step", "p-1", "create-pr")
        md = self.ok("plugin", "plans", "show", "p-1", "--markdown")
        self.assertIn("open PR", md, "the resolved text a reader needs is still there")
        self.assertNotIn("anchor", md)
        self.assertNotIn("anchor", self.ok("plugin", "plans", "show", "step-2", "--markdown"))

        shown = self.data("plugin", "plans", "show", "p-1")
        by_def = {s.get("def"): s for s in shown["steps"]}
        self.assertEqual(by_def["create-pr"]["anchor"], "pr", "`--json` carries it")
        self.assertNotIn("anchor", by_def[None],
                         "a step of its own words is not resolved at all")
        # And the stored step holds no such field: the definition owns it, like the name.
        self.assertNotIn("anchor", self._doc()["plans"][0]["steps"][1])

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
        self.assertIn("plan-2", md)
        self.assertIn("a bare plan", md)
        self.assertIn("do the thing", md)
        # And the empty plan, which is the far end of the same axis: a record with an id
        # and nothing else is a heading, not a traceback.
        self.assertIn("plan-3", _plans()._markdown({"id": "p-3"}))

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

    def test_a_forged_row_cannot_forge_one_on_the_comment_either(self):
        """The same property, on the path that now matters. The test above builds a plan
        with no `steps`, so it pins the WALK — and the pull request comment is the other
        renderer, and the one that actually has the table a forged row is aiming at. Every
        stored scalar on a step still goes through `_cell`, so a newline is the `\\n` it is
        and a pipe is escaped, and the plan's table has exactly one row per step however
        the fields are spelled. The one field allowed to keep its newlines is `output`, and
        it is not in this table at all — see the block test below."""
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        md = _plans()._markdown(
            {"id": "p-1", "title": "t",
             "steps": [{"id": "s-1", "display": "a\nb", "name": "c|d",
                        "owner": "e\n| x | y |", "progress": "f\ng",
                        "why": "h|i", "gate": "j\nk"},
                       {"id": "s-2", "name": "the second"}]})

        for escaped in ("a\\nb", "c\\|d", "e\\n\\| x \\| y \\|", "f\\ng", "h\\|i", "j\\nk"):
            self.assertIn(escaped, md)
        self.assertNotIn("\n| x | y |", md)
        # One fold per step and not a line more: every table row below `## steps` is a
        # `field | value` row of a step's own body, and nothing above forged one.
        below = md.split("## steps", 1)[1]
        self.assertEqual(below.count("<summary>"), 2, below)
        for row in below.splitlines():
            if row.startswith("|") and not row.startswith("| --- "):
                self.assertEqual(row.count(" | "), 1, row)

    _DUMP = ("Scope & Objectives\n"
             "\n"
             "- The change adds one field to a step and one rule to the renderer.\n"
             "  - Nothing else in the plugin moves.\n"
             "\n"
             "Change Contract\n"
             "\n"
             "- A step may carry its own finished output, and the PR comment dumps it.\n"
             "  - The gate is prose, as it is for merge.\n")

    def _approved(self) -> None:
        """A plan whose first step holds an approved contract, written the way one arrives.

        By hand into the file, because that is the only way it ever gets there: no verb
        writes `output`, so a test that used one would be testing a door that does not
        exist.
        """
        self.ok(*_create("ship a change", "get it approved", "write it"))
        self.edit_step("s-1", output=self._DUMP, progress="done")

    def test_a_dumped_output_reaches_the_pull_request_as_the_markdown_it_is(self):
        """The requirement the field exists for, and the decision that replaced the
        blockquote. A change approval is approved as markdown prose and has to arrive on
        the pull request as that prose — headed, nested, readable — rather than as one
        escaped line (the first failure) or as a wall of somebody else's quoted text (the
        second). So the block is lifted out of the step's own fold into a contract section
        of its own and rendered line for line.

        OPEN and not collapsed, which is the Phase-3 half: when a plan has a contract it is
        the most-read thing on the comment, and a fold is a click between the reader and the
        text they came to check the diff against."""
        self._approved()
        md = self.ok("plugin", "plans", "show", "p-1", "--markdown")

        for line in self._DUMP.strip().split("\n"):
            self.assertIn(line.strip(), md)
        # As separate lines and not as one escaped run — the first failure this replaces.
        self.assertNotIn("\\n", md)
        # As markdown and not inside a quote — the second.
        self.assertIn("\nChange Contract", md)
        self.assertNotIn("> Change Contract", md)
        self.assertIn("  - Nothing else in the plugin moves.", md)
        # In the contract section, and that section is above the folds and outside every
        # one of them: nothing between the heading and the text is a `<details>`.
        self.assertIn("\n## contract\n", md)
        contract = md.split("## contract", 1)[1].split("## steps", 1)[0]
        self.assertIn("### step-1 output", contract)
        self.assertIn("Change Contract", contract)
        self.assertNotIn("<details>", contract)
        # And the step it belongs to points at it rather than carrying a second copy.
        self.assertIn("[step-1 output](#step-1-output)", md)

    def test_a_dumped_output_cannot_forge_a_row_of_a_step_s_own_table(self):
        """The anti-forgery property, kept by WHERE the block goes rather than by quoting
        it. The dump is lifted out of every step's fold entirely, into the contract section,
        so a line spelled like a markdown table row draws a row of the DUMP and never a row
        of a step. That is what the blockquote used to buy, at the cost of the field's
        whole reason to exist; the property every stored SCALAR still holds by escaping is
        pinned next door in `test_a_forged_row_cannot_forge_one_here_either`."""
        self._approved()
        self.edit_step("s-1", output="| a | b |\n| --- | --- |\n| c | d |")
        md = self.ok("plugin", "plans", "show", "p-1", "--markdown")

        self.assertIn("| a | b |", md)
        # Not one line of the dump is below `## steps`, which is where every step's own
        # table lives: the dump is in a section the folds do not contain.
        below = md.split("## steps", 1)[1]
        for row in ("| a | b |", "| c | d |"):
            self.assertNotIn(row, below)
        # And the forged rows are up in the contract section, above the folds.
        self.assertLess(md.index("| a | b |"), md.index("## steps"))

    def test_a_step_carrying_a_dump_still_renders_beside_the_rest(self):
        """The decision the block rule used to force the other way round. A table cell is
        one line, so the walker degraded a whole plan into bullets the moment one step
        carried a dump — which is exactly when the plan had the most to say. The comment
        lifts the block OUT of the step instead: every step gets the same fold whether or
        not it carries one, and the one that does links to the contract section.

        The walker still has the old rule and still needs it — `show <step> --markdown` is
        walked, and a block in a cell there would be the same wall of text."""
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        flat = {"id": "p-1", "title": "t",
                "steps": [{"id": "s-1", "name": "get it approved", "output": "a\nb"},
                          {"id": "s-2", "name": "write it"}]}
        md = _plans()._markdown(flat)

        # One fold per step (dump or no dump), plus the one collapse the detailed record
        # sits behind. No metadata block here — the plan carries only id/title/steps.
        self.assertEqual(md.count("<summary>"), len(flat["steps"]) + 1)
        self.assertIn("get it approved", md)
        self.assertIn("[step-1 output](#step-1-output)", md)
        self.assertIn("### step-1 output", md)
        self.assertIn("\na\nb\n", md)
        self.assertFalse(_plans()._tabular(flat["steps"]))

    def test_the_steps_are_drawn_as_a_graph_with_one_node_and_one_edge_per_dep(self):
        """The dependency graph, which is the half of a plan no rendering had before: the
        deps were a cell of ids and the shape of the job was left to be assembled in
        somebody's head. GitHub draws a ```mermaid fence natively, so the comment ships one.

        A dep naming a step that is not in the plan draws nothing. That is a defect the
        three doors report in words, and a graph that invented a node for it would be
        drawing a plan that does not exist."""
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        md = _plans()._markdown(
            {"id": "p-1", "title": "t",
             "steps": [{"id": "s-1", "name": "write it"},
                       {"id": "s-2", "name": "review it", "deps": ["s-1"]},
                       {"id": "s-3", "name": "merge it", "deps": ["s-2"]}]})
        graph = md.split("```mermaid", 1)[1].split("```", 1)[0]

        self.assertIn("flowchart LR", graph)
        for node in ("step-1 · write it", "step-2 · review it", "step-3 · merge it"):
            self.assertIn(node, graph)
        self.assertEqual([ln.strip() for ln in graph.splitlines() if "-->" in ln],
                         ["n_s_1 --> n_s_2", "n_s_2 --> n_s_3"])

        loose = _plans()._markdown(
            {"id": "p-1", "title": "t",
             "steps": [{"id": "s-1", "name": "write it", "deps": ["s-9"]}]})
        self.assertNotIn("-->", loose.split("```mermaid", 1)[1].split("```", 1)[0])
        # And the steps table says the same thing the graph does: the dep is DRAWN, so the
        # defect is not hidden, and it is not linked, because there is no row to land on.
        self.assertIn("| step-9 |", loose)
        self.assertNotIn("[step-9]", loose)

    def test_an_open_step_is_coloured_apart_from_a_skipped_one(self):
        """The state most worth seeing on a live plan is what REMAINS, and before this it
        was the one state with no class — so it fell through to mermaid's default fill,
        which is the grey the legend already spends on `skipped`. A step still to do then
        read as one deliberately abandoned, which is close to the opposite.

        Every step now carries a class, the three not-done states are each distinct, and
        the legend names all four and matches what the nodes render as. Amber stays the one
        salient state — it is the only one needing a person — so `todo`'s blue is calm."""
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        plan = {"id": "p-1", "title": "t", "steps": [
            {"id": "s-1", "name": "write it", "progress": "done"},
            {"id": "s-2", "name": "do it", "deps": ["s-1"]},                      # open
            {"id": "s-3", "name": "drop it", "progress": "skipped", "why": "n/a",
             "deps": ["s-2"]},
            {"id": "s-4", "name": "merge", "gate": "Andrew: merge?", "deps": ["s-3"]}]}
        graph = _plans()._markdown(plan).split("```mermaid", 1)[1].split("```", 1)[0]

        # The open step is classed, and classed apart from the skipped one.
        self.assertIn("classDef todo", graph)
        self.assertIn("class n_s_2 todo", graph)
        self.assertIn("class n_s_3 skipped", graph)
        self.assertNotIn("class n_s_2 skipped", graph)
        # And every not-done state is named in the legend that follows the fence.
        legend = _plans()._markdown(plan).split("```", 2)[2]
        for named in ("done", "still to do", "skipped", "waits on a human"):
            self.assertIn(named, legend)

    def test_the_status_line_counts_what_is_settled_and_names_the_gate(self):
        """The one line at the top, and the two things it has to get right: the counts, and
        the difference between a gate that is HOLDING the plan up and one five steps out.
        A status line that called both "blocked" would say it on every plan that has a
        merge, which is all of them."""
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        plan = {"id": "p-1", "title": "t", "steps": [
            {"id": "s-1", "name": "write it", "progress": "done"},
            {"id": "s-2", "name": "review it", "progress": "skipped", "deps": ["s-1"]},
            {"id": "s-3", "name": "merge it", "display": "merge", "deps": ["s-2"],
             "gate": "Andrew: merge it?"}]}

        def status(pl):
            # The status line lives in the detailed record now, not at a fixed index — found
            # by its label rather than by counting lines above it.
            return next(l for l in _plans()._markdown(pl).splitlines()
                        if l.startswith("**Status:**"))

        line = status(plan)
        self.assertIn("in progress", line)
        self.assertIn("1/3 done", line)
        self.assertIn("1 skipped", line)
        self.assertIn("blocked at the merge gate", line)
        # The gate the plan has not reached yet is named and is not called a block.
        plan["steps"][1]["progress"] = "open"
        ahead = status(plan)
        self.assertIn("merge gate ahead", ahead)
        self.assertNotIn("blocked", ahead)
        # And a progress word nobody here wrote is NAMED rather than counted as open:
        # `progress` is an open vocabulary and a hand-edit is where that word comes from.
        plan["steps"][1]["progress"] = "waiting on Andrew"
        self.assertIn("waiting on Andrew", status(plan))

    def test_a_dump_that_is_not_a_string_takes_the_ordinary_path(self):
        """The fallback, in the spirit of the field-nobody-wrote-this-for test above. The
        block rule is a fact about a KEY, and a hand-edited file can put a list or a number
        under that key — so the rule asks what the value is and hands anything but a string
        back to the walker rather than raising in front of somebody's merge."""
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        for value, expected in (([{"objective": "met"}], "met"), (7, "7"),
                                ({"aligned": "partial"}, "partial")):
            md = _plans()._markdown(
                {"id": "p-1", "title": "t",
                 "steps": [{"id": "s-1", "name": "review it", "output": value,
                            "deps": ["s-0"]}]})
            self.assertIn(expected, md)

    def test_show_prints_the_dump_too_so_somebody_proofreads_it(self):
        """A field that only ever appeared on a pull request comment would be a field
        nobody reads until it is posted. The terminal rendering prints it as well, one line
        per line under the step — split first, so a line of it cannot draw a step row in
        the view where a step row IS a line."""
        self._approved()
        shown = self.ok("plugin", "plans", "show", "p-1")

        self.assertIn("out   Scope & Objectives", shown)
        self.assertIn("out   Change Contract", shown)
        self.edit_step("s-1", output="approved\ns-9   done      merged")
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("out   s-9   done      merged", shown)
        self.assertFalse([ln for ln in shown.splitlines() if ln.startswith("s-9")])

    def test_json_is_unchanged_by_the_flag_when_a_dump_is_present(self):
        """`--markdown` is a rendering and not a projection: the `--json` payload is the
        plan record either way, with the dump in it as the string it is stored as. What
        reads the payload is another plugin, and a flag that reshaped it for a human would
        break that reader for the sake of the same view it already had."""
        self._approved()
        self.assertEqual(self.data("plugin", "plans", "show", "p-1", "--markdown"),
                         self.data("plugin", "plans", "show", "p-1"))
        self.assertEqual(
            self.data("plugin", "plans", "show", "p-1", "--markdown")["steps"][0]["output"],
            self._DUMP)

    def test_the_flag_is_declared_on_show_and_nowhere_else(self):
        """One command renders a plan for a PR, and it is the one that reads a single plan
        by id — so there is no verb that could render the whole store as markdown."""
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        self.assertIn("--markdown", _plans_args("show"))
        for command in _plans_commands():
            if command != "show":
                self.assertNotIn("--markdown", _plans_args(command))


class LayoutTest(PlansSandbox):
    """Phase 3: what is OPEN on the pull request and what is behind a fold.

    The one part of this rendering whose layout IS pinned, and deliberately — the rest of
    the comment is tested for what it says rather than for how it is arranged, because a
    test that pinned the arrangement would be the per-field template the renderer exists not
    to be. The arrangement here is not incidental: it is the whole change. Four things a
    reader needs without clicking, in the order they need them, and then one collapsed
    `<details>` per step so a plan with twenty steps is still a page somebody can scan.
    """

    def _plan(self) -> dict:
        """A plan with one of everything the layout has to place, and a change record so the
        human-first sections above the detailed record have something to draw."""
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        hour = 3600
        return {"id": "p-1", "kind": "plan", "display": "board: ship it",
                "title": "ship the thing", "created_at": 1000,
                "change": {"path": "shaped",
                           "cause": "the cap was too low",
                           "solution": "raise the cap and pin it with a test",
                           "verification": {"commit": "abc1234", "result": "green"},
                           "review": {"commit": "abc1234", "reviewer": "reviewer-x",
                                      "findings": "no majors"},
                           "human_checks": "- Upload a 20MB file and confirm it works"},
                "steps": [
                    {"id": "s-1", "display": "impl", "name": "write it",
                     "progress": "done"},
                    {"id": "s-2", "display": "approve", "name": "get it approved",
                     "progress": "done", "deps": ["s-1"],
                     "output": "Change Contract\n\n- it folds\n"},
                    {"id": "s-3", "display": "merge", "name": "merge it", "deps": ["s-2"],
                     "gate": "Andrew: merge it?"}],
                "changelog": [
                    {"at": 1000 + hour, "by": "w", "action": "tick",
                     "detail": "s-1 open → done"},
                    {"at": 1000 + 2 * hour, "by": "w", "action": "tick",
                     "detail": "s-2 open → done"}]}

    def test_the_open_sections_come_in_the_order_a_reader_needs_them(self):
        """HUMAN-FIRST, and the order is the argument: what you need to do, then what changed
        and why, then the evidence, and only then the detailed record. The first screenful is
        for the person deciding what THEY still have to do, so the human checks and the open
        gate are the top of the page and the plan's own detail is one click down.
        """
        plan = self._plan()
        md = _plans()._markdown(plan)

        order = [md.index(x) for x in
                 ("## What you need to do", "## What changed and why", "## Agent evidence",
                  "## Detailed record")]
        self.assertEqual(order, sorted(order), md)
        # `What you need to do` is the first section: nothing but the heading above it.
        head = md.split("## What you need to do", 1)[0]
        self.assertNotIn("##", head)
        # The human's questions are up top: the manual check and the open gate.
        need = md.split("## What you need to do", 1)[1].split("## What changed", 1)[0]
        self.assertIn("Upload a 20MB file", need)
        self.assertIn("Andrew: merge it?", need)
        # And the shaped plan itself — graph, contract, steps — is COLLAPSED under the
        # detailed record, not above it. The mermaid graph appears only down there.
        above, below = md.split("## Detailed record", 1)
        self.assertNotIn("```mermaid", above)
        self.assertIn("<details>", below)
        self.assertIn("```mermaid", below)
        self.assertIn("## steps", below)
        self.assertIn("Change Contract", below)

    def test_every_step_is_a_fold_titled_with_its_name_state_and_elapsed(self):
        """`{id} · {display} — {name} | {state} | {elapsed}`, one per step, no exceptions —
        a step with a contract and a step with nothing on it get the same fold, so a reader
        scanning the titles is reading one shape rather than three.

        The elapsed half goes WITH its separator when there is nothing to measure. A plan
        that has not run yet would otherwise carry a dangling `| ` on every title, which is
        a column pretending to have a value.
        """
        plan = self._plan()
        md = _plans()._markdown(plan)
        titles = [ln.split("</a>", 1)[1].removesuffix("</summary>")
                  for ln in md.splitlines() if ln.startswith("<summary><a id=")]

        self.assertEqual(titles[:2], [
            "step-1 · impl — write it | done | 1h 0m",
            "step-2 · approve — get it approved | done | 1h 0m"])
        # An open step that IS unblocked reads as running rather than as finished.
        self.assertTrue(titles[2].startswith("step-3 · merge — merge it | open · gate | "),
                        titles[2])
        self.assertTrue(titles[2].endswith(" so far"), titles[2])
        # And when there is nothing to measure at all, the elapsed goes WITH its separator.
        bare = _plans()._markdown({"id": "p-1", "title": "t", "steps": [
            {"id": "s-1", "display": "impl", "name": "write it"}]})
        self.assertIn('<summary><a id="step-1"></a>step-1 · impl — write it | open</summary>',
                      bare)
        # One fold per step, plus the metadata block, plus the change-record remainder (this
        # plan's change carries a non-promoted `path`), plus the one collapse the whole
        # detailed record sits behind.
        self.assertEqual(md.count("<details>"), len(plan["steps"]) + 3)
        # The title is the anchor everything else in the comment links a step by.
        self.assertIn('<summary><a id="step-1"></a>step-1 ·', md)
        self.assertIn("[step-1](#step-1)", md)

    def test_a_fold_carries_the_whole_step_including_a_field_nobody_wrote_this_for(self):
        """The safety net, moved rather than dropped. A step's undrawn fields used to be
        filed in the comment-wide metadata block at the bottom, next to the checkout path;
        they now render inside that step's own fold. A note about step 3 belongs under step
        3 — and a field this file has never heard of still has to land somewhere, which is
        the property the walk was there for in the first place.
        """
        plan = self._plan()
        plan["steps"][2]["owner"] = "lead-x"
        plan["steps"][0]["mood"] = "cheerful"
        plan["steps"][0]["notes"] = [{"text": "reworked after review", "by": "w"}]
        md = _plans()._markdown(plan)
        folds = md.split("## steps", 1)[1].split("<details>")

        self.assertIn("| mood | cheerful |", folds[1])
        self.assertIn("reworked after review", folds[1])
        self.assertIn("| owner | lead-x |", folds[3])
        # And the contract is a LINK from its step, not a second copy of the prose.
        self.assertIn("[step-2 output](#step-2-output)", folds[2])
        self.assertNotIn("Change Contract", md.split("## steps", 1)[1])
        # `root: false` is the default said out loud and draws nothing — a plan that marks
        # a second start marks every OTHER step false, and a `root | no` under all of them
        # is a column of nothing. A true one is a claim and draws.
        for s in plan["steps"]:
            s["root"] = False
        self.assertNotIn("| root |", _plans()._markdown(plan))
        plan["steps"][0]["root"] = True
        self.assertEqual(_plans()._markdown(plan).count("| root |"), 1)

    def test_the_blank_lines_a_collapsible_needs_are_there_on_every_fold(self):
        """The gotcha the whole layout rests on: without a blank line after `</summary>`
        and another before `</details>`, GitHub renders the body as literal text — so a
        plan would arrive on a pull request as a wall of pipe characters and raw HTML.

        Checked on EVERY fold rather than on the first, because the failure is per-block:
        one step whose body starts hard against its summary is one step nobody can read.
        """
        plan = self._plan()
        md = _plans()._markdown(plan)

        # The detailed record now nests the per-step folds inside one outer collapse, so the
        # rule is checked per DELIMITER rather than by splitting on `<details>` (which cannot
        # tell an inner `</details>` from the outer one): every summary is followed by a
        # blank line, and every close is preceded by one.
        self.assertIn("<details>", md)
        for m in re.finditer("</summary>", md):
            self.assertTrue(md[m.end():m.end() + 2] == "\n\n",
                            f"no blank line after a summary: {md[m.end():m.end()+40]!r}")
        for m in re.finditer("</details>", md):
            self.assertTrue(md[m.start() - 2:m.start()] == "\n\n",
                            f"no blank line before a close: {md[m.start()-40:m.start()]!r}")


class TelemetryTest(PlansSandbox):
    """The three stats the pull-request comment grew: per-step elapsed, who closed a step,
    and what the plan burned.

    All three are arranged around the same rule — NEVER A GUESS. A step nothing can be
    measured for gets a blank cell, a plan whose transcripts could not be read gets no token
    line, and neither draws a zero. A zero is the one wrong answer available here: it reads
    as a real measurement of nothing.
    """

    def test_per_step_elapsed_is_measured_from_when_the_step_was_unblocked(self):
        """The figure and the two cases that decide whether it means anything.

        A ROOT is measured from the plan's `created_at`, because that is the first moment
        anybody could have started it. A step with deps is measured from the LAST of them to
        close — which is what takes dependency-blocked time back out, and is the whole
        reason the number is worth drawing: a step that waited a day behind two others and
        then took ten minutes has to read as ten minutes.

        A RE-ENTERED step uses the latest tick. It is ticked, reopened by hand and ticked
        again, and the reading somebody wants is when it was actually finished, not when it
        was first thought to be.
        """
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        hour = 3600
        plan = {"id": "p-1", "title": "t", "created_at": 1000, "steps": [
            {"id": "s-1", "name": "write it", "progress": "done"},
            {"id": "s-2", "name": "review it", "progress": "done", "deps": ["s-1"]},
            {"id": "s-3", "name": "merge it", "progress": "done", "deps": ["s-2"]}],
            "changelog": [
                {"at": 1000 + hour, "by": "w", "action": "tick", "detail": "s-1 open → done"},
                # s-2 closes two hours after s-1 did, and the day s-3 then sat waiting for a
                # human is NOT s-2's time: s-2 is 2h and s-3 is what came after it.
                {"at": 1000 + 3 * hour, "by": "w", "action": "tick",
                 "detail": "s-2 open → done"},
                # s-1 re-entered and ticked again, LATER — but that must not move s-2's
                # start, which is s-1's last close, so s-2 is re-measured from it.
                {"at": 1000 + 4 * hour, "by": "w", "action": "tick",
                 "detail": "s-3 open → done"}]}

        took = _plans()._timings(plan, plan["steps"])
        self.assertEqual(took["s-1"], (hour, False))        # root: from created_at
        self.assertEqual(took["s-2"], (2 * hour, False))    # from s-1's close, not creation
        self.assertEqual(took["s-3"], (hour, False))
        self.assertIn("1h 0m", _plans()._markdown(plan))

        # Re-entered: the LATEST tick is the one that counts, for the step itself and for
        # everything measuring from it.
        plan["changelog"].append(
            {"at": 1000 + 5 * hour, "by": "w", "action": "tick", "detail": "s-1 open → done"})
        again = _plans()._timings(plan, plan["steps"])
        self.assertEqual(again["s-1"], (5 * hour, False))
        # s-2 closed BEFORE s-1's second tick, so it is now negative and is dropped rather
        # than drawn: a step that took minus two hours is not a fact about the job.
        self.assertNotIn("s-2", again)

    def test_a_step_that_was_never_unblocked_is_left_blank_and_an_open_one_runs(self):
        """The two absences, and why one of them is not zero.

        A step whose deps have not closed was never unblocked — there is no moment to
        measure from, so nothing is claimed. A step that IS unblocked and still open has a
        real start and no end, so it gets a running figure marked as running; a bare number
        there would read as finished.
        """
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        plan = {"id": "p-1", "title": "t", "created_at": int(time.time()) - 7200, "steps": [
            {"id": "s-1", "name": "write it"},
            {"id": "s-2", "name": "review it", "deps": ["s-1"]}]}
        took = _plans()._timings(plan, plan["steps"])
        self.assertNotIn("s-2", took)               # never unblocked: no figure at all
        self.assertTrue(took["s-1"][1], took)       # unblocked at creation, still running
        self.assertIn("so far", _plans()._markdown(plan))

        # And the third case, which is the one a real plan hits: a step SETTLED by a hand
        # edit, which writes no changelog entry. It is finished, so it must not read as
        # running — and there is no stamp to measure to, so it gets no figure at all.
        plan["steps"][0]["progress"] = "skipped"
        self.assertEqual(_plans()._timings(plan, plan["steps"]), {})
        self.assertNotIn("so far", _plans()._markdown(plan))

    def test_a_token_total_is_compact_at_every_magnitude(self):
        """Andrew's format: the unit steps so the mantissa stays roughly in [0.1, 100), so
        the figure is the same WIDTH whether a plan burned twelve thousand tokens or two
        billion. The boundaries are the whole of it — 100k is `0.1m` and not `100k`."""
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        for count, expected in ((0, "0"), (900, "900"), (999, "999"), (1000, "1k"),
                                (12_000, "12k"), (99_000, "99k"), (100_000, "0.1m"),
                                (1_000_000, "1m"), (1_500_000, "1.5m"), (12_000_000, "12m"),
                                (100_000_000, "0.1b"), (1_000_000_000, "1b"),
                                (2_400_000_000, "2.4b")):
            self.assertEqual(_plans()._mag(count), expected, count)

    def test_tokens_that_could_not_be_read_are_absent_and_never_a_zero(self):
        """The degradation, which is most of what this stat is. Nothing in switchboard
        counts tokens — the number is read out of somebody else's log format, per agent,
        through a subprocess that is refused across a tree boundary. So every way of failing
        has to end in the line simply not being there, because a `**Tokens:** 0` on a pull
        request is a claim that the job was free."""
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        plan = {"id": "p-1", "title": "t", "steps": [{"id": "s-1", "name": "write it"}]}
        self.assertNotIn("**Tokens:**", _plans()._markdown(plan))
        # Every shape a broken read could put there, and none of them draws a line.
        for broken in (None, {}, {"total": None}, {"total": "lots"}, "unavailable"):
            self.assertEqual(_plans()._tokens(dict(plan, tokens=broken)), "", broken)
        # A transcript that is not there is None — an agent NOT COUNTED — and not a zero,
        # which is the distinction the "3 of 5 agents read" half of the line rests on.
        self.assertIsNone(_plans()._burned(str(Path(self.tmp.name) / "nope.jsonl")))

    def test_a_transcript_is_counted_once_per_message_and_not_once_per_block(self):
        """The one subtlety of the file being read: a Claude Code transcript is one JSONL
        record per CONTENT BLOCK, and every block of an assistant message repeats that whole
        message's `usage`. Summing the records doubles a real session's total, by a factor
        that moves with how many tool calls each turn made — so usage is banked against the
        message id and counted once. The non-token integers sitting in the same dict
        (`iterations`, and whatever is added to it next) are left out for the same reason:
        the figure has to be tokens and nothing else."""
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        turn = {"id": "msg_1", "usage": {"input_tokens": 10, "output_tokens": 5,
                                         "cache_creation_input_tokens": 100,
                                         "cache_read_input_tokens": 1000,
                                         "iterations": 7, "service_tier": "standard"}}
        path = Path(self.tmp.name) / "t.jsonl"
        path.write_text("\n".join([
            json.dumps({"type": "assistant", "message": turn}),   # same message, two blocks
            json.dumps({"type": "assistant", "message": turn}),
            "{ this line is torn and is skipped rather than fatal",
            json.dumps({"type": "user", "message": {"role": "user"}}),
            json.dumps({"type": "assistant", "message": dict(turn, id="msg_2")}),
        ]) + "\n")
        self.assertEqual(_plans()._burned(str(path)), 2 * 1115)


class RecordTest(PlansSandbox):
    """The change record: the shared landing lifecycle, held whether or not a plan exists.

    Phase 3's separation. A DIRECT change has no plan and no change-approval step; it gets a
    record only when it needs somewhere to keep landing metadata, and `record` is that verb.
    A SHAPED change is a plan, and its record is born with it at shaping entry — sparse, and
    invisible in `show` until a landing fact lands, so a fresh plan reads as it did before
    the record existed. A legacy document carries neither `kind` nor `change` and reads as
    the plain plan it is: the field is additive and nothing silently rewrites a stored one.
    """

    def test_record_makes_a_change_record_with_the_direct_skeleton(self):
        """`record` is a change on the direct path, born with the fixed execution+landing
        skeleton. It shares the plan id space and its own file, and `show`/`list`/`--json`
        all read it."""
        made = self.data("plugin", "plans", "record", "raise the upload timeout",
                         "--display", "board: raise the upload timeout",
                         "--reason", "a bounded fix, no plan")
        self.assertEqual(made["id"], "p-1")
        self.assertEqual(made["kind"], "record")
        self.assertEqual(made["change"]["path"], "direct")
        self.assertIsNone(made["change"]["phase"])
        # The STORED document carries the fixed skeleton — a direct change is no longer
        # stepless: the steps are written to the file, not just added by the renderer.
        stored = self._doc()["plans"][0]
        self.assertEqual([s.get("def") for s in stored["steps"]],
                         ["implementation", "review", "merge-human-review",
                          "create-pr", "merge"])

        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("change", shown)
        self.assertIn("direct", shown)
        self.assertIn("implement the change", shown)   # the skeleton's first step, resolved

        listed = self.ok("plugin", "plans", "list")
        self.assertIn("p-1", listed)
        self.assertIn("direct", listed)                # the tier tag, in place of "record"

    def test_the_direct_skeleton_is_a_linear_chain_in_run_order(self):
        """The skeleton is a fixed list, chained linearly in the order it runs — each step
        after the one before, no branches, and no `obliged_by` so `validate` stays clean."""
        self.data("plugin", "plans", "record", "raise the timeout",
                  "--display", "board: raise the timeout")
        steps = self._doc()["plans"][0]["steps"]
        self.assertEqual(len(steps), 5)
        # merge-human-review sits BEFORE create-pr: the checklist must exist when the PR opens.
        self.assertEqual([s["def"] for s in steps],
                         ["implementation", "review", "merge-human-review",
                          "create-pr", "merge"])
        # Linear: the first is a root, every later one waits on exactly its predecessor.
        self.assertEqual(steps[0]["deps"], [])
        for earlier, later in zip(steps, steps[1:]):
            self.assertEqual(later["deps"], [earlier["id"]])
        # Named steps, not freetext: the label resolves from the library, none is hand-copied.
        for s in steps:
            self.assertIsNone(s["name"])
            self.assertIsNone(s["obliged_by"])
        # It validates with no defects — a plain named skeleton trips no obligation warning.
        self.assertIn("no defects", self.ok("plugin", "plans", "validate", "p-1"))

    def test_a_legacy_stepless_record_still_renders(self):
        """A record written before the skeleton has no `steps`. It must keep rendering — no
        migration injects steps into it, and `show`/`list` read it without error."""
        self.data("plugin", "plans", "record", "an older direct change",
                  "--display", "board: older change")
        doc = self._doc()
        doc["plans"][0].pop("steps", None)          # a pre-skeleton record
        doc["plans"][0].pop("next_step", None)
        self._save(doc)
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("direct", shown)              # still legible as a direct change
        self.assertNotIn("(no steps yet)", shown)   # a record, not a plan, so no plan prompt
        self.assertIn("p-1", self.ok("plugin", "plans", "list"))

    def test_a_record_takes_a_request_and_carries_it(self):
        """`--request` seeds the human ask the record exists to carry to the PR."""
        made = self.data("plugin", "plans", "record", "raise the timeout",
                         "--display", "board: raise the timeout",
                         "--request", "uploads over 10MB time out; make them not")
        self.assertEqual(made["change"]["request"],
                         "uploads over 10MB time out; make them not")
        self.assertIn("uploads over 10MB", self.ok("plugin", "plans", "show", "p-1"))

    def test_a_record_needs_a_board_name_like_a_plan(self):
        """The same door `create` keeps: a record owns a header line and is refused without
        one, and the refusal reaches a machine reader in `data`."""
        code, _, _ = self.sb("plugin", "plans", "record", "no display", "--json")
        self.assertNotEqual(code, 0)

    def test_a_shaped_plan_is_born_with_its_record_but_reads_as_before(self):
        """`create` is shaping entry, so the plan carries a shaped record from birth — but
        sparse, so `show` says nothing new until a landing fact lands. The record is in the
        file and in `--json`; the human view is unchanged."""
        made = self.data("plugin", "plans", "create", "a shaped job",
                         "--display", "board: a shaped job", "--step", "impl = write it")
        self.assertEqual(made["kind"], "plan")
        self.assertEqual(made["change"]["path"], "shaped")
        self.assertEqual(made["change"]["phase"], "shaping")
        # A fresh shaped plan's record holds no landing fact, so `show` does not draw a
        # change section — the plan reads exactly as it did before Phase 3.
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertNotIn("path      shaped", shown)

    def test_template_use_starts_a_shaped_plan_with_a_record_too(self):
        """A template starts a shaped plan, so it is born with the same shaped change record
        `create` gives — the two make-a-plan verbs agree."""
        made = self.data("plugin", "plans", "template", "use", "docs")
        self.assertEqual(made["kind"], "plan")
        self.assertEqual(made["change"]["path"], "shaped")
        self.assertEqual(made["change"]["phase"], "shaping")

    def test_a_landed_fact_draws_the_record_on_a_shaped_plan(self):
        """Once a landing fact is written into the record by hand — a verification, a PR —
        `show` draws the change section. Structured facts render nested."""
        self.data("plugin", "plans", "create", "a shaped job",
                  "--display", "board: a shaped job", "--step", "impl = write it")
        doc = self._doc()
        doc["plans"][0]["change"]["verification"] = {
            "commit": "abc1234", "check": "pytest tests", "result": "green"}
        doc["plans"][0]["change"]["pr"] = {"number": 42, "head": "abc1234"}
        self._save(doc)
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("change", shown)
        self.assertIn("verification", shown)
        self.assertIn("abc1234", shown)

    def test_a_legacy_document_has_no_kind_and_reads_as_a_plan(self):
        """A plan written before Phase 3 carries neither `kind` nor `change`. It reads,
        lists and renders as the plain plan it is — the field is additive and nothing here
        rewrites a stored document to add it."""
        self.data(*_create("an older job", "shape the work"))
        doc = self._doc()
        plan = doc["plans"][0]
        plan.pop("kind", None)
        plan.pop("change", None)
        self._save(doc)
        # Reads without error, is not a record, and its change section is silent.
        again = self.data("plugin", "plans", "show", "p-1")
        self.assertNotIn("kind", again)
        self.assertNotIn("change", again)
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("shape the work", shown)
        self.assertNotIn("path      ", shown)
        listed = self.ok("plugin", "plans", "list")
        self.assertIn("1 step", listed)

    def test_record_is_a_declared_verb_with_its_flags(self):
        """The verb is registered and takes the flags the direct path needs."""
        self.ok("plugin", "plans", "guide")     # import the module the registry reads
        self.assertIn("record", _plans_commands())
        args = _plans_args("record")
        for flag in ("title", "--display", "--request", "--note", "--reason"):
            self.assertIn(flag, args)

    def test_name_step_refuses_a_record(self):
        """A library step cannot be named onto a change record: it carries the FIXED skeleton
        and is not extended step by step — a job that needs more is a shaped plan. Refused at
        the door, with the reason in `data` for a machine reader; nothing is added."""
        self.data("plugin", "plans", "record", "raise the timeout",
                  "--display", "board: raise the timeout")
        before = list(self._doc()["plans"][0]["steps"])
        code, out, _ = self.sb("plugin", "plans", "name-step", "p-1", "review", "--json")
        self.assertNotEqual(code, 0)
        self.assertIn("change record", json.loads(out)["data"]["error"])
        # Nothing was added: the record still carries only the skeleton it was born with.
        self.assertEqual(self._doc()["plans"][0]["steps"], before)

    def test_the_guide_names_the_direct_and_shaped_paths(self):
        """The guide is coherent with the two-path model: a shaped plan and, for a direct
        change, a change record made only when landing facts are needed. It keeps the phrase
        the spawn-side test pins."""
        out = " ".join(self.ok("plugin", "plans", "guide").split())
        self.assertIn("heading for a change that will land", out)   # still pinned
        for token in ("DIRECT change", "CHANGE RECORD", "sb plugin plans record",
                      "SHAPING first"):
            self.assertIn(token, out)

    def test_the_board_tags_a_record_with_its_tier_and_counts_its_skeleton(self):
        """A record now draws a step chart like a plan, so the board header tags it with its
        TIER (`direct`) — that is what tells the two apart — and counts the skeleton steps."""
        from defaults.plugins.plans import board
        rec = {"id": "p-1", "kind": "record", "display": "raise timeout", "condition": "live",
               "change": {"path": "direct"},
               "steps": [{"id": "s-1"}, {"id": "s-2"}, {"id": "s-3"},
                         {"id": "s-4"}, {"id": "s-5"}]}
        header = board._header(rec, False)
        self.assertIn("direct", header)
        self.assertIn("5 steps", header)
        self.assertNotIn("record", header)

    def test_the_board_falls_back_to_a_line_when_a_document_has_no_chart(self):
        """A stepless document — a legacy record, or a sparse shaped placeholder — is no
        longer a bare header: the board draws a fallback line from its phase and gist."""
        from defaults.plugins.plans import board
        sparse = {"id": "p-1", "kind": "plan", "display": "shape it", "steps": [],
                  "change": {"path": "shaped", "phase": "shaping"},
                  "notes": [{"text": "Investigating the widget bug", "by": "x", "at": 0}]}
        line = board._empty_line(sparse)
        self.assertIn("shaping", line)
        self.assertIn("Investigating the widget bug", line)


class ChangeRecordLifecycleTest(PlansSandbox):
    """The change record's identity fields and the lifecycle it validates.

    Two things Phase 3 owns beyond the record existing: the combined change approval is an
    IDENTITY (the plan revision and contract digest it was approved against), not a boolean;
    and the lifecycle DESCRIBES AND VALIDATES the record — a warning, never a refusal, when
    the record presents itself as sanctioned before it was. The phases stay advisory: nothing
    here polices when a step ran, only what the record claims about itself.
    """

    def test_the_combined_approval_is_an_identity_and_round_trips(self):
        """The approved change approval binds a plan revision and a contract digest, recorded
        by hand into `change.approval`, and it round-trips and renders."""
        self.data("plugin", "plans", "create", "a shaped job",
                  "--display", "board: a shaped job", "--step", "impl = write it")
        doc = self._doc()
        doc["plans"][0]["change"]["approval"] = {
            "plan_revision": "p-1@r3", "contract_digest": "sha256:abcd1234",
            "by": "andrew", "at": 1787880000}
        doc["plans"][0]["change"]["phase"] = "execution"
        self._save(doc)
        stored = self._doc()["plans"][0]["change"]["approval"]
        self.assertEqual(stored["plan_revision"], "p-1@r3")
        self.assertEqual(stored["contract_digest"], "sha256:abcd1234")
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("approval", shown)
        self.assertIn("sha256:abcd1234", shown)

    def test_execution_before_a_recorded_approval_is_a_defect(self):
        """A shaped record claiming execution without a complete combined approval identity
        is drawn red and reported by `validate`, and never refused."""
        self.data("plugin", "plans", "create", "a shaped job",
                  "--display", "board: a shaped job", "--step", "impl = write it")
        doc = self._doc()
        doc["plans"][0]["change"]["phase"] = "execution"     # no approval recorded
        self._save(doc)
        defects = self.data("plugin", "plans", "validate", "p-1")["plans"][0]["defects"]
        joined = " ".join(defects)
        self.assertIn("sanctioned without the complete approval identity", joined)
        # Recording the approval clears it.
        doc = self._doc()
        doc["plans"][0]["change"]["approval"] = {"plan_revision": "p-1@r1",
                                                 "contract_digest": "sha256:x", "by": "a"}
        self._save(doc)
        self.assertEqual(self.data("plugin", "plans", "validate", "p-1")["plans"][0]["defects"],
                         [])

    def test_an_incomplete_approval_identity_does_not_sanction_execution(self):
        """A truthy approval object is not enough: both identity fields are load-bearing."""
        self.data("plugin", "plans", "create", "a shaped job",
                  "--display", "board: a shaped job", "--step", "impl = write it")
        doc = self._doc()
        doc["plans"][0]["change"]["phase"] = "execution"
        doc["plans"][0]["change"]["approval"] = {"by": "andrew", "at": 1787880000}
        self._save(doc)
        defects = self.data("plugin", "plans", "validate", "p-1")["plans"][0]["defects"]
        joined = " ".join(defects)
        self.assertIn("`plan_revision`", joined)
        self.assertIn("`contract_digest`", joined)

    def test_a_direct_record_never_trips_the_approval_check(self):
        """A direct change has no approval and never claims one; its phase stays null, so the
        sanction check does not apply to it."""
        self.data("plugin", "plans", "record", "a direct fix", "--display", "board: fix")
        self.assertEqual(self.data("plugin", "plans", "validate", "p-1")["plans"][0]["defects"],
                         [])

    def test_landing_before_a_pr_is_a_defect(self):
        """A change at or past landing with no PR recorded is an order the lifecycle cannot
        have."""
        self.data("plugin", "plans", "create", "a shaped job",
                  "--display", "board: a shaped job", "--step", "impl = write it")
        doc = self._doc()
        c = doc["plans"][0]["change"]
        c["phase"] = "landing"
        c["approval"] = {"plan_revision": "r1", "contract_digest": "d"}  # so only the PR trips
        self._save(doc)
        joined = " ".join(self.data("plugin", "plans", "validate", "p-1")["plans"][0]["defects"])
        self.assertIn("before it is on a pull request", joined)

    def test_a_phase_the_lifecycle_does_not_have_is_not_a_defect(self):
        """`phase` is advisory and open like `progress`: an unrecognised word is a job's own,
        not a defect, so the lifecycle checks simply skip it."""
        self.data("plugin", "plans", "create", "a shaped job",
                  "--display", "board: a shaped job", "--step", "impl = write it")
        doc = self._doc()
        doc["plans"][0]["change"]["phase"] = "waiting on the vendor"
        self._save(doc)
        self.assertEqual(self.data("plugin", "plans", "validate", "p-1")["plans"][0]["defects"],
                         [])

    def test_an_optional_fresh_main_handoff_renders_only_when_present(self):
        """The fresh-main handoff is optional and recorded only when used — absent on every
        ordinary record, and rendered as a first-class fact when a hand-edit adds it."""
        self.data("plugin", "plans", "create", "a shaped job",
                  "--display", "board: a shaped job", "--step", "impl = write it")
        self.assertNotIn("handoff", self.ok("plugin", "plans", "show", "p-1"))
        doc = self._doc()
        doc["plans"][0]["change"]["handoff"] = {"from": "lead-1", "to": "main-2",
                                                "at": 1787880000}
        self._save(doc)
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("handoff", shown)
        self.assertIn("main-2", shown)


class HumanFirstCommentTest(PlansSandbox):
    """Phase 4: the PR comment reads human-first. What a person still has to do is the first
    screenful; the shaped plan and its observability are collapsed under a detailed record;
    and a DIRECT change renders the same shape from its record, with no empty or invented
    plan under it. The idempotent marker/upsert is Phase 3's and is unchanged.
    """

    def _md(self, plan_id: str = "p-1") -> str:
        return self.ok("plugin", "plans", "show", plan_id, "--markdown")

    def test_the_four_sections_come_human_first_and_in_order(self):
        """What you need to do, what changed and why, the evidence, then the detailed record.
        The plan's own graph is collapsed below, not in the first screenful."""
        self.data("plugin", "plans", "create", "raise the cap",
                  "--display", "board: raise the cap", "--step", "impl = raise it")
        doc = self._doc()
        doc["plans"][0]["change"].update({
            "cause": "the cap was too low", "solution": "raise it and pin a test",
            "verification": {"commit": "abc1234", "result": "green"},
            "human_checks": "- Upload a 20MB file and confirm it works"})
        self._save(doc)
        md = self._md()
        order = [md.index(x) for x in
                 ("## What you need to do", "## What changed and why", "## Agent evidence",
                  "## Detailed record")]
        self.assertEqual(order, sorted(order), md)
        self.assertIn("Upload a 20MB file", md.split("## What changed", 1)[0])
        self.assertNotIn("```mermaid", md.split("## Detailed record", 1)[0])

    def test_human_checks_render_as_tickable_checkboxes(self):
        """A list of human checks renders as GitHub checkboxes (`- [ ]`), so a person reading
        the PR on a phone runs the list by ticking it. Open gates tick the same way."""
        self.data("plugin", "plans", "create", "raise the cap",
                  "--display", "board: raise the cap", "--step", "impl = raise it")
        doc = self._doc()
        doc["plans"][0]["change"]["human_checks"] = [
            "Upload a 50MB file on a real device", "Confirm the progress bar reaches 100%"]
        doc["plans"][0]["steps"].append(
            {"id": "s-9", "name": "merge it", "display": "merge", "progress": "open",
             "gate": "Andrew: land it?"})
        self._save(doc)
        need = self._md().split("## What you need to do", 1)[1].split("## ", 1)[0]
        self.assertIn("- [ ] Upload a 50MB file on a real device", need)
        self.assertIn("- [ ] Confirm the progress bar reaches 100%", need)
        # The open gate is in the list too, and it is a checkbox as well.
        gate_line = next(ln for ln in need.splitlines() if "Andrew: land it?" in ln)
        self.assertTrue(gate_line.startswith("- [ ] "), gate_line)

    def test_nothing_needed_says_so_outright(self):
        """A change whose record ANSWERED the question with none says so, in as many words,
        rather than leaving the section empty for a reader to interpret."""
        self.data("plugin", "plans", "create", "a tidy job",
                  "--display", "board: a tidy job", "--step", "impl = do it")
        doc = self._doc()
        doc["plans"][0]["change"]["human_checks"] = "none"
        self._save(doc)
        md = self._md()
        need = md.split("## What you need to do", 1)[1].split("## ", 1)[0]
        self.assertIn("Nothing—agent verification covers this change.", need)

    def test_an_unanswered_change_is_not_told_agent_verification_covers_it(self):
        """"Nothing for you" is the line a person acts on by closing the tab, so it is only
        said where somebody said it. A record nobody has filled — a legacy plan from before
        the change record, or a comment posted before the list was written — says it is
        unrecorded instead of claiming an assurance nobody gave."""
        self.data("plugin", "plans", "create", "a tidy job",
                  "--display", "board: a tidy job", "--step", "impl = do it")
        need = self._md().split("## What you need to do", 1)[1].split("## ", 1)[0]
        self.assertNotIn("agent verification covers", need)
        self.assertIn("Not recorded", need)

    def test_a_skipped_human_review_step_is_itself_the_answer(self):
        """Skipping `merge-human-review` is a person's work considered and found
        unnecessary, so it answers the question even when the skip wrote no output."""
        self.data("plugin", "plans", "create", "a tidy job",
                  "--display", "board: a tidy job", "--step", "impl = do it")
        self.ok("plugin", "plans", "name-step", "p-1", "merge-human-review")
        doc = self._doc()
        step = next(s for s in doc["plans"][0]["steps"]
                    if s.get("def") == "merge-human-review")
        step["progress"], step["why"] = "skipped", "a one-line docs change"
        self._save(doc)
        need = self._md().split("## What you need to do", 1)[1].split("## ", 1)[0]
        self.assertIn("Nothing—agent verification covers this change.", need)

    def test_the_none_sentinel_renders_as_nothing_not_the_word(self):
        """`human_checks: "none"` is the sentinel for a change with nothing for a human; it
        renders as the sentence, never the bare word."""
        self.data("plugin", "plans", "record", "a direct fix", "--display", "board: fix")
        doc = self._doc()
        doc["plans"][0]["change"]["human_checks"] = "none"
        self._save(doc)
        need = self._md().split("## What you need to do", 1)[1].split("## ", 1)[0]
        self.assertIn("Nothing—agent verification covers this change.", need)
        self.assertNotIn("- none", need)

    def test_a_direct_record_renders_human_first_with_its_skeleton(self):
        """A direct change's record drives the human-first sections, and its fixed skeleton
        renders in the collapsed detailed record — a real graph, not an invented plan, drawn
        from the steps the record was born with."""
        made = self.data("plugin", "plans", "record", "raise the timeout",
                         "--display", "board: raise the timeout",
                         "--request", "uploads over 10MB time out")
        doc = self._doc()
        doc["plans"][0]["change"].update({
            "solution": "raise the timeout to 60s",
            "verification": {"commit": "def5678", "result": "green"}})
        self._save(doc)
        md = self._md()
        self.assertTrue(md.lstrip().startswith("#"))
        self.assertIn("## What you need to do", md)
        self.assertIn("uploads over 10MB time out", md)          # the request
        self.assertIn("raise the timeout to 60s", md)            # the solution
        self.assertIn("def5678", md)                             # the evidence
        # The human-first sections come before the detailed record; the skeleton graph is
        # collapsed under it, not in the first screenful.
        above = md.split("## Detailed record", 1)[0]
        self.assertNotIn("## how it runs", above)
        below = md.split("## Detailed record", 1)[1]
        self.assertIn("## how it runs", below)                   # the real skeleton graph
        self.assertIn("implementation", below)

    def test_agent_evidence_binds_the_reviewed_commit_and_review(self):
        """The evidence section names the reviewed commit and carries the verification and
        the independent review, so a reader sees what was checked, not a claim that it was."""
        self.data("plugin", "plans", "create", "a shaped job",
                  "--display", "board: a shaped job", "--step", "impl = write it")
        doc = self._doc()
        doc["plans"][0]["change"].update({
            "verification": {"commit": "c0ffee1", "check": "pytest tests", "result": "green"},
            "review": {"commit": "c0ffee1", "reviewer": "reviewer-y",
                       "findings": "one minor, fixed"}})
        self._save(doc)
        ev = self._md().split("## Agent evidence", 1)[1].split("## Detailed record", 1)[0]
        self.assertIn("Reviewed commit", ev)
        self.assertIn("c0ffee1", ev)
        self.assertIn("reviewer-y", ev)
        self.assertIn("one minor, fixed", ev)

    def test_a_structured_review_carries_its_identity_fixes_and_open_majors(self):
        """The review is an identity, not a verdict word: WHO reviewed, WHICH head, the
        fixes they applied against it and any major still open. A structured record renders
        every one of those into the evidence a reader gets — an unresolved major that only
        the author can see is how a PR comes to say `reviewed` while a defect stands."""
        self.data("plugin", "plans", "record", "a direct fix", "--display", "board: fix")
        doc = self._doc()
        doc["plans"][0]["change"].update({
            "human_checks": "none",
            "review": {"commit": "9f1c2ab", "reviewer": "reviewer-cache-keys",
                       "findings": [{"severity": "major", "state": "unresolved",
                                     "what": "the cache key drops the tenant id"}],
                       "fixes": [{"commit": "3aa77e0", "what": "renamed the stale local"}]}})
        self._save(doc)
        ev = self._md().split("## Agent evidence", 1)[1]
        for part in ("9f1c2ab", "reviewer-cache-keys", "major", "unresolved",
                     "the cache key drops the tenant id", "3aa77e0",
                     "renamed the stale local"):
            with self.subTest(part=part):
                self.assertIn(part, ev)

    def test_the_detailed_record_still_carries_the_whole_plan_collapsed(self):
        """Nothing a human could want is gone — the graph, the contract, the per-step folds
        and the metadata are all still there, one click down under the detailed record."""
        self.data("plugin", "plans", "create", "a shaped job",
                  "--display", "board: a shaped job",
                  "--step", "impl = write it", "--lib", "review")
        doc = self._doc()
        doc["plans"][0]["steps"][0]["output"] = "Change Contract\n\n- the thing"
        self._save(doc)
        below = self._md().split("## Detailed record", 1)[1]
        self.assertIn("<details>", below)
        self.assertIn("```mermaid", below)
        self.assertIn("## steps", below)
        self.assertIn("## contract", below)

    def test_the_change_record_remainder_preserves_every_unpromoted_fact(self):
        """The facts the first three sections do not lift — the approved contract, the
        approval identity, the PR head, the landing approval and outcome, the fresh-main
        handoff — are still the record and must not vanish. They render in a collapsed change-
        record block under the detailed record, for a direct change and a shaped one alike."""
        made = self.data("plugin", "plans", "record", "raise the timeout",
                         "--display", "board: raise the timeout")
        doc = self._doc()
        doc["plans"][0]["change"].update({
            "contract": "Change Contract\n\n- raise it to 60s",
            "approval": {"plan_revision": "p-1@r1", "contract_digest": "sha256:aa",
                         "by": "andrew"},
            "pr": {"number": 42, "head": "def5678"},
            "landing": {"head": "def5678", "by": "andrew", "outcome": "merged"},
            "handoff": {"from": "lead-1", "to": "main-2"}})
        self._save(doc)
        below = self._md().split("## Detailed record", 1)[1]
        self.assertIn("change record", below)                 # the collapsed remainder block
        self.assertIn("Change Contract", below)               # the approved contract, whole
        self.assertIn("sha256:aa", below)                     # the approval identity
        self.assertIn("42", below)                            # the PR
        self.assertIn("merged", below)                        # the landing outcome
        self.assertIn("main-2", below)                        # the handoff
        # And promoted content is not duplicated into the remainder.
        doc = self._doc(); doc["plans"][0]["change"]["cause"] = "UNIQUE-CAUSE-TOKEN"
        self._save(doc)
        remainder = self._md().split("<summary>change record</summary>", 1)[1]
        self.assertNotIn("UNIQUE-CAUSE-TOKEN", remainder)

    def test_scope_limitations_and_baseline_reach_the_first_screenful(self):
        """Phase 4 requires scope boundaries in `what changed`, and known limitations or an
        evidenced baseline failure in `agent evidence`; the verification environment and the
        reviewer's fixes ride along inside their own facts."""
        self.data("plugin", "plans", "create", "a shaped job",
                  "--display", "board: a shaped job", "--step", "impl = write it")
        doc = self._doc()
        doc["plans"][0]["change"].update({
            "solution": "raise the cap",
            "scope": "server config only; no client change",
            "verification": {"commit": "c0ffee1", "environment": "ci ubuntu-22",
                             "result": "green"},
            "review": {"commit": "c0ffee1", "reviewer": "rev-y",
                       "fixes": ["tightened a log line"]},
            "limitations": "does not cover chunked uploads",
            "baseline": "test_flaky_x was already failing on main"})
        self._save(doc)
        md = self._md()
        why = md.split("## What changed and why", 1)[1].split("## Agent evidence", 1)[0]
        self.assertIn("Scope boundaries", why)
        self.assertIn("server config only", why)
        ev = md.split("## Agent evidence", 1)[1].split("## Detailed record", 1)[0]
        self.assertIn("ci ubuntu-22", ev)                     # verification environment
        self.assertIn("tightened a log line", ev)             # reviewer fixes
        self.assertIn("does not cover chunked uploads", ev)   # known limitations
        self.assertIn("already failing on main", ev)          # baseline failure
        # They are change-record facts, not renderer-only magic: the ordinary record view
        # exposes them too, so an author can inspect what the PR will consume.
        shown = self.ok("plugin", "plans", "show", "p-1")
        self.assertIn("scope", shown)
        self.assertIn("limitations", shown)
        self.assertIn("baseline", shown)

    def test_a_mirrored_shaped_contract_renders_once(self):
        """The approved contract is mirrored into the record and approval-step output; an
        exact mirror remains one fact in the collapsed detailed record, not two copies."""
        self.data("plugin", "plans", "create", "a shaped job",
                  "--display", "board: a shaped job", "--step", "impl = write it",
                  "--lib", "change-approval")
        doc = self._doc()
        contract = "Change Contract\n\n- change only the timeout"
        doc["plans"][0]["change"]["contract"] = contract
        approval = next(s for s in doc["plans"][0]["steps"]
                        if s.get("def") == "change-approval")
        approval["output"] = contract
        self._save(doc)
        self.assertEqual(self._md().count("change only the timeout"), 1)

    def test_a_malformed_step_falls_to_the_walk_even_with_a_change_record(self):
        """A non-dict in the steps list is corruption, and the render falls back to the walk
        rather than the human-first path — even when a change record is present. The
        human-first path renders an empty steps list, which would silently drop the
        legitimate step beside the bad one; the walk shows everything."""
        self.ok("plugin", "plans", "list")          # loads the plugin module for `_plans`
        p = {"id": "p-1", "title": "t", "change": {"path": "shaped", "cause": "x"},
             "steps": ["corrupt", {"id": "s-1", "name": "the real step"}]}
        md = _plans()._markdown(p)
        # The legitimate step is not dropped, and the human-first sections are not drawn.
        self.assertIn("the real step", md)
        self.assertNotIn("## What you need to do", md)

    def test_create_pr_says_the_comment_is_refreshed_on_material_change(self):
        """Phase 4: the authoritative comment is updated when review fixes, the head, or
        landing state materially change what a human should see — not only at merge."""
        about = " ".join(self.ok("plugin", "plans", "library", "create-pr").split())
        self.assertIn("REFRESHED, NOT ONLY AT MERGE", about)
        self.assertIn("materially changes", about)

    def test_the_marked_comment_body_still_upserts_but_show_hides_the_nonce(self):
        """The Phase-3 identity is preserved: the posted body carries the marker line, and
        `show --markdown` — a human rendering — does not leak the per-PR nonce marker."""
        self.data("plugin", "plans", "create", "a job", "--display", "board: a job",
                  "--step", "impl = do it")
        # The nonce marker is added by `comment`, never by the human-facing render.
        self.assertNotIn("switchboard-plan:", self._md())


class LibrarySemanticsTest(PlansSandbox):
    """Phase 3's library semantics, read off `library <name>`. These pin the change-record
    connection and the review's structure; the full composition-aware prose pass is Phase 5.

    The structural fields — anchors, obliges, displays — are pinned by CatalogueTest and are
    unchanged here; this class is only about the semantics Phase 3 added to the `about`.
    """

    def _about(self, name: str) -> str:
        """`library <name>`, whitespace-collapsed — the renderer reflows the prose, so a
        multi-word token would otherwise straddle a wrap."""
        return " ".join(self.ok("plugin", "plans", "library", name).split())

    def test_review_is_independent_structured_and_recorded_by_the_owner(self):
        """`review` names a fresh agent, a target commit, the major/minor/nit classification,
        the reviewer's own minor fixes, and one writer for the result: the reviewer returns
        the structure and the worktree owner records it for identity-bound landing."""
        about = self._about("review")
        for token in ("FRESH agent", "COMMIT", "MAJOR", "MINOR", "NIT", "change record",
                      "review: {commit, reviewer, findings, fixes}", "worktree owner",
                      "single writer"):
            self.assertIn(token, about)

    def test_change_approval_is_combined_and_recorded(self):
        """`change-approval` is the shaped path's single sign-off on solution, plan and
        contract, recorded into the change record; a direct change never gets one."""
        about = self._about("change-approval")
        for token in ("COMBINED", "solution", "contract", "change record", "DIRECT"):
            self.assertIn(token, about)

    def test_create_pr_requires_evidence_and_serves_the_direct_path(self):
        """`create-pr` requires current verification and a resolved review, read from the
        record by identity; and a direct change reaches its PR here with no plan."""
        about = self._about("create-pr")
        for token in ("verification", "RESOLVED review", "DIRECT change", "comment <record>"):
            self.assertIn(token, about)

    def test_merge_consumes_an_identity_without_rerunning(self):
        """`merge` reads the record's approval and evidence and checks the head, and does not
        rerun the tests or the review to rebuild confidence."""
        about = self._about("merge")
        for token in ("CONSUMES IDENTITIES", "combined change `approval`",
                      "human landing approval", "`landing`", "does NOT rerun", "head"):
            self.assertIn(token, about)

    def test_the_definitions_point_at_canonical_homes_not_re_teach_procedure(self):
        """Phase 3's bounded six-definition de-dup: a definition POINTS at the preset, role
        or runtime that owns a procedure rather than re-teaching it. Bounded on purpose — the
        composition-wide rewrite across protocol/roles/guide/library is Phase 5. The removed
        strings are the evidence the cleanup happened, not just more prose."""
        ca = self._about("change-approval")
        self.assertIn("sb presets design-gate", ca)          # points at the format's owner
        self.assertNotIn("Order it for READING", ca)         # removed: the format re-teaching
        self.assertNotIn("two-space indents under", ca)      # removed: the nesting mechanic
        cp = self._about("create-pr")
        self.assertNotIn("what has already been tested", cp)  # removed: the PR-description how-to
        hr = self._about("merge-human-review")
        self.assertNotIn("MARKDOWN-READY NESTING", hr)       # removed: the rendering mechanic
        rv = self._about("review")
        self.assertNotIn("markdown-ready nesting", rv)       # removed: the rendering mechanic
        # And the step-specific facts the tests pin elsewhere are still there — the trim did
        # not gut the definitions, it removed what a role/runtime/preset already owns.
        self.assertIn("EMPTY THE `gate` FIELD as you tick", ca)
        self.assertIn("renders the plan AS IT STANDS AT THAT MOMENT", cp)

    def test_the_shipped_library_still_has_exactly_its_six_definitions(self):
        """Phase 3 changed semantics, not the shipped set: the six definitions and their
        anchors and obligations are what CatalogueTest pins, and nothing here adds a
        seventh or renames one."""
        listed = self.ok("plugin", "plans", "library")
        for key in ("change-approval", "create-pr", "merge", "merge-human-review",
                    "plan-review", "review"):
            self.assertIn(key, listed)


class LandingMergeTest(PlansSandbox):
    """`merge`: the landing verb, and the head comparison that is its whole reason to exist.

    Landing used to be a hand-run `gh pr merge` with the approved-head-versus-live-head check
    written as prose an agent was asked to eyeball. These pin the three decisions that made it
    a verb instead: it REFUSES on any head that is not the one the landing approval and the
    recorded evidence cover, it merges and RECORDS what happened when they all agree, and it
    RUNS NO TEST, BUILD OR REVIEW on that path — by landing, all of that is evidence already
    on the record, and re-earning it is the cost this design exists to remove.

    GitHub is faked at the exact `gh api` argv the plugin builds, so every one of these still
    crosses the real dispatch, the real store and the real rendering. Nothing here reaches
    github.com.
    """

    HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
    OTHER = "9876543210fedcba9876543210fedcba98765432"

    @contextlib.contextmanager
    def github(self, *, head=HEAD, state="open", merged=False, branch="worker-x",
               merge_error=None, comment_error=None):
        """A pull request, its comments and its merge button, behind the real argv.

        The merge endpoint enforces GitHub's own `sha` precondition, because that is half of
        what makes this fail closed: the plugin compares once and then hands the head it
        compared back to GitHub, so a branch that moves in between is refused by the side
        that owns it rather than by nobody.
        """
        seen: list[list] = []
        comments: list[dict] = []
        box = {"merged": merged, "head": head, "next_id": 100, "deleted": None}
        real_run = subprocess.run

        def run(argv, *args, **kwargs):
            argv = list(argv)
            seen.append(argv)
            if argv[:2] != ["gh", "api"]:
                return real_run(argv, *args, **kwargs)
            method = argv[argv.index("--method") + 1] if "--method" in argv else "GET"
            target = next(str(a) for a in argv if str(a).startswith("repos/"))
            if target.endswith("/merge"):
                if merge_error:
                    return subprocess.CompletedProcess(argv, 1, "", merge_error)
                if json.loads(kwargs["input"]).get("sha") != box["head"]:
                    return subprocess.CompletedProcess(
                        argv, 1, "", "HTTP 409: Head branch was modified")
                box["merged"] = True
                return subprocess.CompletedProcess(
                    argv, 0, json.dumps({"merged": True, "sha": "f" * 40}), "")
            if "/git/refs/heads/" in target:
                box["deleted"] = target.rsplit("/heads/", 1)[-1]
                return subprocess.CompletedProcess(argv, 0, "", "")
            if "/pulls/" in target:
                return subprocess.CompletedProcess(argv, 0, json.dumps(
                    {"number": int(target.rsplit("/", 1)[-1]), "state": state,
                     "merged": box["merged"],
                     "head": {"sha": box["head"], "ref": branch}}), "")
            if comment_error:
                return subprocess.CompletedProcess(argv, 1, "", comment_error)
            if "--paginate" in argv:
                return subprocess.CompletedProcess(argv, 0, json.dumps([comments]), "")
            body = json.loads(kwargs["input"])["body"]
            if method == "POST":
                row = {"id": box["next_id"], "body": body}
                box["next_id"] += 1
                comments.append(row)
            else:
                cid = int(str(argv[argv.index("--method") + 2]).rsplit("/", 1)[-1])
                row = next(r for r in comments if r["id"] == cid)
                row["body"] = body
            return subprocess.CompletedProcess(argv, 0, json.dumps(row), "")

        with mock.patch("subprocess.run", side_effect=run):
            yield _Fake(seen, comments, box)

    def approved(self, *, head=HEAD, **over) -> None:
        """A change record standing exactly where landing begins: approved, evidenced, on a
        PR, every recorded head the same commit. Written by hand, which is how a record is
        filled — `merge` is the only verb that writes to one after `record --request`."""
        self.data("plugin", "plans", "record", "raise the upload timeout",
                  "--display", "board: raise the upload timeout")
        doc = self._doc()
        change = doc["plans"][0]["change"]
        change.update({
            "phase": "landing",
            "cause": "the client timeout was shorter than the server's",
            "pr": {"number": 42, "head": head},
            "verification": {"commit": head, "check": "pytest tests/test_upload.py",
                             "result": "green"},
            "review": {"commit": head, "reviewer": "reviewer-uploads",
                       "findings": "no majors"},
            "landing": {"head": head, "by": "andrew", "at": 1700000000},
        })
        change.update(over)
        self._save(doc)

    def landing(self) -> dict:
        return self._doc()["plans"][0]["change"]["landing"]

    # -- it refuses ------------------------------------------------------------

    def test_merge_refuses_when_the_live_head_is_not_the_head_that_was_approved(self):
        """THE case the verb exists for. The branch moved under a landing approval, so the
        approval covers a change that is no longer the one about to land — and the merge is
        refused before any mutation, with the reason a machine reader can act on."""
        self.approved()
        with self.github(head=self.OTHER) as gh:
            code, out, _ = self.sb("plugin", "plans", "merge", "p-1", "--pr", "42", "--json")

        self.assertNotEqual(code, 0)
        data = json.loads(out)["data"]
        self.assertFalse(data["merged"])
        self.assertEqual(data["expected"], self.HEAD)
        self.assertEqual(data["found"], self.OTHER)
        self.assertIn("REFUSING TO MERGE", data["error"])
        # Nothing was merged and nothing was written: no PUT was ever sent, and the record
        # carries no outcome for a landing that did not happen.
        self.assertFalse([c for c in gh.seen if "PUT" in [str(a) for a in c]])
        self.assertFalse(gh.box["merged"])
        self.assertNotIn("outcome", self.landing())

    def test_merge_refuses_when_no_human_has_approved_the_landing(self):
        """Fail closed on the absence too. A record with the evidence but no landing approval
        is a change nobody agreed to land, and an absent approval must refuse as loudly as a
        moved head — the two are the same defect and the quiet one is the dangerous one."""
        self.approved(landing=None)
        with self.github() as gh:
            code, out, _ = self.sb("plugin", "plans", "merge", "p-1", "--pr", "42", "--json")

        self.assertNotEqual(code, 0)
        self.assertIn("no human landing approval", json.loads(out)["data"]["error"])
        self.assertFalse(gh.box["merged"])
        # It refused before it even asked GitHub anything.
        self.assertFalse([c for c in gh.seen if list(c[:2]) == ["gh", "api"]])

    # -- it lands --------------------------------------------------------------

    def test_merge_lands_the_approved_head_and_records_the_outcome(self):
        """The clean path: every recorded head agrees with the live one, so the verb merges
        it ITSELF rather than telling an agent to, writes what happened to
        `change.landing.outcome`, and refreshes the one authoritative comment in place —
        after the write, so the comment renders the state the change ended in."""
        self.approved()
        with self.github() as gh:
            data = self.data("plugin", "plans", "merge", "p-1", "--pr", "42")

        self.assertTrue(data["merged"])
        self.assertTrue(gh.box["merged"])
        outcome = self.landing()["outcome"]
        self.assertEqual(outcome["result"], "merged")
        self.assertEqual(outcome["method"], "merge")
        self.assertEqual(outcome["head"], self.HEAD)
        self.assertEqual(outcome["pr"], 42)
        self.assertEqual(outcome["sha"], "f" * 40)
        self.assertEqual(outcome["comment"], "updated")
        # One comment, and it carries the outcome — so the write happened before the post.
        self.assertEqual(len(gh.comments), 1)
        self.assertIn("merged", gh.comments[0]["body"])
        # The landing approval a human gave is untouched; only the outcome was added.
        self.assertEqual(self.landing()["by"], "andrew")
        self.assertEqual(self.landing()["head"], self.HEAD)

    def test_a_merge_that_lands_and_a_comment_that_does_not_is_recorded_as_both(self):
        """Partial state stays visible. The merge cannot be undone once GitHub has taken it,
        so a failure after that point is recorded as what actually completed and returned as
        a failure — never reported as a clean landing, and never retried as a merge."""
        self.approved()
        with self.github(comment_error="HTTP 502: Bad Gateway") as gh:
            code, _, said = self.sb("plugin", "plans", "merge", "p-1", "--pr", "42")

        self.assertNotEqual(code, 0)
        self.assertTrue(gh.box["merged"])
        self.assertIn("IS MERGED", said)
        self.assertIn("do not merge again", said)
        outcome = self.landing()["outcome"]
        self.assertEqual(outcome["result"], "merged")
        self.assertTrue(outcome["comment"].startswith("failed:"))

    def test_a_shaped_change_cannot_land_without_the_combined_change_approval(self):
        """`validate` reports a shaped record past execution with no `change.approval` as a
        defect and refuses nothing, which is right everywhere except here: landing is the
        moment unsanctioned work becomes everybody's, so at the merge that warning has to be
        a refusal. A DIRECT change has no approval and is never asked for one — the same
        record on the direct path lands."""
        self.approved()
        doc = self._doc()
        doc["plans"][0]["change"]["path"] = "shaped"
        self._save(doc)
        with self.github() as gh:
            code, out, _ = self.sb("plugin", "plans", "merge", "p-1", "--pr", "42", "--json")
        self.assertNotEqual(code, 0)
        error = json.loads(out)["data"]["error"]
        self.assertIn("change.approval", error)
        self.assertIn("plan_revision", error)
        self.assertFalse(gh.box["merged"])

        # Recorded, and the same record lands.
        doc = self._doc()
        doc["plans"][0]["change"]["approval"] = {
            "plan_revision": 4, "contract_digest": "sha256:abc", "by": "andrew", "at": 1}
        self._save(doc)
        with self.github() as gh:
            self.data("plugin", "plans", "merge", "p-1", "--pr", "42")
        self.assertTrue(gh.box["merged"])

    def test_the_recorded_evidence_has_to_cover_the_approved_head_as_well(self):
        """The approval is not the only identity landing consumes. Evidence belongs to the
        commit it ran on, so a verification naming a different commit — or naming none at
        all — is evidence for a different change, and merging on it would be landing an
        approval whose basis was never checked. Refused the same way a moved head is."""
        self.approved(verification={"commit": self.OTHER, "check": "pytest", "result": "ok"})
        with self.github() as gh:
            code, out, _ = self.sb("plugin", "plans", "merge", "p-1", "--pr", "42", "--json")
        self.assertNotEqual(code, 0)
        self.assertIn("change.verification", json.loads(out)["data"]["error"])
        self.assertFalse(gh.box["merged"])

        # And a review that names no commit at all is the same refusal, not a pass.
        self.approved(review={"reviewer": "reviewer-uploads", "findings": "no majors"})
        with self.github() as gh:
            code, out, _ = self.sb("plugin", "plans", "merge", "p-1", "--pr", "42", "--json")
        self.assertNotEqual(code, 0)
        self.assertIn("does not name a commit", json.loads(out)["data"]["error"])
        self.assertFalse(gh.box["merged"])

    def test_a_squash_and_a_branch_deletion_are_asked_for_and_recorded(self):
        """The two flags that change what landing DOES, and both end up on the record —
        `cleanup` beside `outcome`, because a merge that landed and a branch that did not go
        is a real half-finished state and the record is where it stays visible."""
        self.approved()
        with self.github() as gh:
            data = self.data("plugin", "plans", "merge", "p-1", "--pr", "42",
                             "--method", "squash", "--delete-branch")

        self.assertTrue(data["merged"])
        self.assertEqual(gh.box["deleted"], "worker-x")
        landing = self.landing()
        self.assertEqual(landing["outcome"]["method"], "squash")
        self.assertEqual(landing["cleanup"], dict(landing["cleanup"],
                                                  deleted=True, branch="worker-x"))

    # -- and it re-earns nothing ----------------------------------------------

    def test_the_merge_path_runs_no_test_build_or_review_of_any_kind(self):
        """The hard constraint, pinned as a test because prose has never held it.

        Merge CONSUMES the recorded evidence and never re-earns it: by the time landing
        begins the tests have run, on a commit the record names, and rerunning a passing
        check to make the merge feel safer is the whole cost this design removes. So the only
        programs this path may reach for are `gh` — GitHub — and this repo's own `sb`, which
        the rendering asks who is alive — with `git` and `herdr` under that. Anything else
        appearing here is the regression.
        """
        self.approved()
        with self.github() as gh:
            self.data("plugin", "plans", "merge", "p-1", "--pr", "42")

        # `gh` is GitHub; `sb`, `git` and `herdr` are how the rendering under this asks who
        # is alive and where the worktree is. None of the four is a test or build runner, and
        # a fifth program appearing on this path is the regression this pins.
        programs = {Path(str(call[0])).name for call in gh.seen}
        self.assertTrue(programs <= {"gh", "sb", "git", "herdr"}, programs)
        flat = " ".join(" ".join(str(a) for a in call) for call in gh.seen)
        for banned in ("pytest", "unittest", "npm", "yarn", "tox", "cargo", "coverage",
                       "lint", "review"):
            self.assertNotIn(banned, flat)
        # And the GitHub calls are exactly the landing ones: read the PR, merge it, upsert
        # the comment. No checks endpoint, no runs endpoint, nothing re-verified.
        endpoints = [next(str(a) for a in call if str(a).startswith("repos/"))
                     for call in gh.seen if list(call[:2]) == ["gh", "api"]]
        self.assertTrue(all("/pulls/42" in e or "/issues/42/comments" in e
                            or "/issues/comments/" in e for e in endpoints), endpoints)

    # -- the surface -----------------------------------------------------------

    def test_merge_is_a_declared_verb_and_the_library_step_points_at_it(self):
        """The verb is registered with its flags, and `merge.json`'s command is it — a step
        still handing an agent `comment` would leave the head check unrun by anybody."""
        self.ok("plugin", "plans", "guide")     # import the module the registry reads
        self.assertIn("merge", _plans_commands())
        args = _plans_args("merge")
        for flag in ("plan", "--pr", "--method", "--delete-branch", "--reason"):
            self.assertIn(flag, args)
        spec = json.loads((self.catalogue("library") / "merge.json").read_text())
        self.assertEqual(spec["command"], "sb plugin plans merge <PLAN> --pr <PR>")

    def test_the_prose_carries_the_feedback_reapproval_and_description_workflows(self):
        """A3 and A5 are text, and text is only delivered if it renders where an agent
        reads it: the guide for the two edges no definition owns, and `create-pr`'s own
        `about` for what the durable PR description has to carry."""
        guide = " ".join(self.ok("plugin", "plans", "guide").split())
        self.assertIn("AFTER THE PR IS OPEN", guide)
        for token in ("observed behaviour and the environment", "COHERENT CAUSE",
                      "only the manual checks the fix invalidated",
                      "A DIFFERENT COMMIT HASH IS NOT BY ITSELF A REAPPROVAL",
                      "INVALIDATED JUDGEMENT, not a different hash"):
            self.assertIn(token, guide)

        about = " ".join(self.ok("plugin", "plans", "library", "create-pr").split())
        for token in ("ROOT CAUSE", "FEATURE INTENT", "SELECTED SOLUTION",
                      "BEHAVIOUR CHANGES", "SCOPE", "VERIFICATION", "INDEPENDENT REVIEW",
                      "RISKS accepted or deferred", "DRAW IT FROM THE RECORD"):
            self.assertIn(token, about)


class _Fake:
    """What the GitHub fake hands a test: every subprocess argv it saw, the PR's comments,
    and the mutable pull request itself."""

    def __init__(self, seen: list, comments: list, box: dict) -> None:
        self.seen, self.comments, self.box = seen, comments, box


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
