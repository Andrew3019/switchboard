"""E2 — a command's output surfaces the caller's own state (spec §2.4).

Three things this unit is, and one it is not:

* **the readout** — what an agent may do, what it may only pass DOWN, where it is attached
  and what config it runs under, printed under the output of the command it just ran;
* **the second call site** — E1 built a `command` key into the resolver and left nothing
  passing one, so a command-keyed rule could not fire at all. `delegate-to-a-lead` is that
  rule, and these pin that it now fires on `sb delegate` and on no turn start;
* **the silence** — the footer is not appended to everything, and it never touches `--json`.

What it is NOT is a second mechanism: the rules come from `guidance.deliver`, the same
function and the same per-`(agent, rule)` cursor the turn-start hook uses, so a `once` rule
said under a command is not said again at the next turn.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import cli, guidance, status as status_mod, store  # noqa: E402
from switchboard.broker import Broker  # noqa: E402

from test_workspace import FakeHerdr  # noqa: E402


class NoteTest(unittest.TestCase):
    """The readout itself. No CLI, no herdr — just what the lines say."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.db = store.connect(path=self.repo / "state.db")
        self.b = Broker(self.db, FakeHerdr(self.repo / "worktrees"), repo=self.repo)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.db.close)

    def note(self, name: str, tier=None) -> str:
        held, passable = self.b.held_for(name), self.b.passable_for(name)
        return guidance.state_note(self.db, name, held=held, delegable=passable - held,
                                   tier=tier)

    def test_it_says_caps_workspace_and_config_and_never_confuses_hold_with_pass_down(self):
        """Obj. 1 and obj. 3 in one readout, because they are one sentence in the output.

        The pass-down half carries the arrow C3 draws in the board's ROLE column, and it is
        said APART from the held set: a researcher that reads its own `write-tracked` as
        something it may do is exactly the confusion `--delegable` exists to prevent.
        """
        store.create_agent(self.db, name="r1", role="researcher", workspace="scope",
                           branch="scope")
        store.seed_capabilities(self.db, "r1", ["spawn"])
        store.grant_capability(self.db, "r1", "write-tracked", delegable=True,
                               granted_by="lead-x", reason="its workers write")

        note = self.note("r1", tier="default")
        self.assertIn("may do: spawn", note)
        self.assertNotIn("may do: spawn, write-tracked", note)
        self.assertIn(f"may pass down only: {guidance.DELEGABLE_MARK}write-tracked", note)
        self.assertIn("workspace scope, branch scope", note)          # obj. 1: attached
        self.assertIn("model tier default", note)                     # obj. 1: config
        self.assertIn("granted since you were spawned:", note)        # obj. 1: grants
        self.assertIn("by lead-x — its workers write", note)
        for line in note.splitlines():
            self.assertTrue(line.startswith(guidance.STATE_MARK), line)

    def test_the_pass_down_arrow_is_the_one_the_board_draws(self):
        """`guidance.DELEGABLE_MARK` is a copy of the character `status` renders, kept out
        of an import because `hooks` loads `guidance` on every turn edge. This is the test
        that makes the copy safe: drift fails here rather than giving one fleet two
        spellings of "may pass down"."""
        self.assertIn(guidance.DELEGABLE_MARK,
                      status_mod._named_mark(guidance.DELEGABLE_MARK, ["fork"]))
        self.assertEqual(guidance.DELEGABLE_MARK, "→")

    def test_a_row_older_than_the_capability_table_is_not_told_it_may_do_nothing(self):
        """Obj. 4's dependency, from the other side: the sets come from `Broker.held_for`,
        which DERIVES them for a row with a NULL `seed_capabilities`. Reading the table
        here instead would print "may do: nothing" to every agent in a store that predates
        the substrate — the one answer that is never true."""
        store.create_agent(self.db, name="old", role="lead")
        note = self.note("old")
        self.assertIn("dispatch, fork, spawn, write-tracked", note)
        self.assertNotIn("may do: nothing", note)


class CommandRuleTest(unittest.TestCase):
    """The rule E1 left inert. `_state_output` is the call site that arms it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.db = store.connect(path=self.repo / "state.db")
        self.b = Broker(self.db, FakeHerdr(self.repo / "worktrees"), repo=self.repo)
        store.create_agent(self.db, name="lead-x", role="lead", workspace="lead-x",
                           branch="lead-x", pane_id="w1:p1")
        store.seed_capabilities(self.db, "lead-x", ["spawn"])
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.db.close)

    def out(self, cmd: str, key, **kw) -> str:
        args = argparse.Namespace(cmd=cmd, json=False, **kw)
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"SB_AGENT": "lead-x"}, clear=False), \
                contextlib.redirect_stdout(buf):
            cli._state_output(args, self.b, self.db, key)
        return buf.getvalue()

    def test_delegate_to_a_lead_now_fires_at_command_time(self):
        """The activation, in one assertion: the shipped rule is keyed `command =
        "delegate"`, and until this call site existed the only resolver call passed None,
        so it matched nothing ever. `once`, so it is said to this agent one time."""
        first = self.out("delegate", "delegate")
        self.assertIn("wants a `lead`, not a `worker`", first)
        self.assertIn(guidance.MARK, first)
        self.assertNotIn("wants a `lead`", self.out("delegate", "delegate"))

    def test_isolation_is_offered_through_the_same_call_site(self):
        """The second `command = "delegate"` row, proved at the real call site rather than
        at the resolver: a rule that matches in `guidance.resolve` and never reaches an
        agent is the failure this test exists to rule out. `fork` is seeded because the row
        is keyed on holding it — a lead that may not fork is never offered the flag."""
        store.grant_capability(self.db, "lead-x", "fork", delegable=False,
                               granted_by="human")
        out = self.out("delegate", "delegate")
        self.assertIn("--isolation own", out)
        self.assertIn(guidance.MARK, out)
        self.assertNotIn("--isolation own", self.out("delegate", "delegate"))

    def test_the_cursor_is_shared_with_the_turn_start_channel(self):
        """Obj. 2 — a complement, not a second mechanism. Both call `guidance.deliver`, so
        a `once` rule spent at a command is spent for the hook too; two cursors would mean
        an agent hearing the same thing twice through two doors."""
        self.out("delegate", "delegate")
        self.assertNotIn("wants a `lead`",
                         guidance.deliver(self.db, "lead-x", command="delegate",
                                          repo=self.repo))

    def test_a_command_rule_stays_off_every_other_command(self):
        """The key is matched, not merely present: the footer under `sb grant` carries this
        agent's state and no delegate advice."""
        note = self.out("grant", "grant")
        self.assertIn(guidance.STATE_MARK, note)
        self.assertNotIn("wants a `lead`", note)


class QuietTest(unittest.TestCase):
    """Obj. 5 — it is not appended to everything, and `--json` stays machine-readable.

    Driven through `cli.main` rather than the helper, because what is being pinned is the
    WIRING: that the tail of `main` runs for a refused command as well as a successful one,
    and that the trivial verbs an agent runs dozens of times a cycle print nothing extra.
    A refusal is the cheap case to drive — no herdr, no spawn — and it is also the case
    where the readout is worth most.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir(parents=True)
        for cmd in (["git", "init", "-q", "-b", "main"],
                    ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                     "commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(cmd, cwd=self.repo, capture_output=True)
        db = store.connect(self.repo)
        store.create_agent(db, name="lead-x", role="lead", workspace="lead-x",
                           branch="lead-x", cwd=str(self.repo))
        store.seed_capabilities(db, "lead-x", ["spawn"])
        db.close()
        cwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(os.chdir, cwd)
        self.env = mock.patch.dict(os.environ, {"SB_AGENT": "lead-x"}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_sb(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_a_non_trivial_command_carries_the_state_even_when_it_is_refused(self):
        code, out, err = self.run_sb("grant", "nobody", "fork")
        self.assertEqual(code, 1)
        self.assertIn("no such agent", err.lower())
        self.assertIn(f"{guidance.STATE_MARK} you are lead-x (lead)", out)

    def test_the_verbs_an_agent_runs_all_day_stay_quiet(self):
        for argv in (["tell", "nobody", "hi"], ["inbox"], ["log"], ["status"]):
            with self.subTest(argv=argv):
                _, out, err = self.run_sb(*argv)
                self.assertNotIn(guidance.STATE_MARK, out + err)

    def test_json_output_is_still_one_json_document(self):
        """The footer is prose for a reader; stdout in `--json` mode is parsed by a
        program, and a line appended to it would break the one machine-readable surface sb
        has."""
        code, out, _ = self.run_sb("--json", "who-holds", "spawn")
        self.assertEqual(code, 0)
        self.assertIn("holders", json.loads(out))
        _, out, _ = self.run_sb("--json", "grant", "nobody", "fork")
        self.assertNotIn(guidance.STATE_MARK, out)


if __name__ == "__main__":
    unittest.main()
