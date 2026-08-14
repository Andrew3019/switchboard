"""Phase 5 — structure: the top-ness stamp, where a spawn lands, who may spawn, and the
tree boundary.

Four rules, and the reason they are one file: they are the same fact asked four ways.
`sb start` stamps a top (5.1); `sb delegate` branches on that stamp rather than on who
happens to hold a worktree (5.2); a role without delegate rights is refused outright
(5.3); and an agent sees its own top's whole tree and no other's (5.4).

The bug all of this replaces is worth stating once. The fork rule used to read
`has_worktree(me)` — worktree POSSESSION — which coincides with top-ness for every agent
that happens to exist, and is not the same fact. `WorktreeIsNotTopnessTest` is the case
where they come apart, proved live before it was proved here.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import store  # noqa: E402
from switchboard.broker import HUMAN, Broker  # noqa: E402

from test_workspace import FakeHerdr  # noqa: E402


class Fixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.db = store.connect(path=self.repo / "state.db")
        self.h = FakeHerdr(self.repo / "worktrees")
        self.b = Broker(self.db, self.h, repo=self.repo)

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def _git_repo(self) -> Path:
        import subprocess
        main = self.repo / "repo"; main.mkdir()
        run = lambda *a: subprocess.run(a, cwd=main, capture_output=True)   # noqa: E731
        run("git", "init", "-q", "-b", "main")
        run("git", "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-q", "--allow-empty", "-m", "x")
        return main

    def _top(self, name: str = "top") -> str:
        """What `sb start` produces: a bare space over the main checkout, stamped."""
        store.create_agent(self.db, name=name, role="lead", workspace=name,
                           cwd=str(self.repo), pane_id="w1:p1", is_top=True)
        return name


# ---------------------------------------------------------------------------
# 5.1 — the stamp
# ---------------------------------------------------------------------------


class TopStampTest(Fixture, unittest.TestCase):
    """`sb start` is the only path that creates a top, and now the only path that says so.

    Before this, the only way to answer "was this created by `sb start`" was to infer it
    from `parent IS NULL AND branch IS NULL` — two other columns that correlate with
    top-ness by accident. The stamp is a fact of its own so that nothing downstream has to
    re-derive it.
    """

    def test_sb_start_stamps_the_agent_it_creates(self):
        b = Broker(self.db, self.h, repo=self._git_repo())
        name = b.start()
        self.assertTrue(store.get_agent(self.db, name)["is_top"])
        self.assertTrue(b.is_top(name))

    def test_a_delegated_agent_is_never_stamped(self):
        """The stamp has exactly one writer. A second would be a second definition of what
        a top is, and the two would drift."""
        kid = self.b.delegate("t", role="worker", me=self._top())
        self.assertFalse(store.get_agent(self.db, kid)["is_top"])
        self.assertFalse(self.b.is_top(kid))

    def test_the_stamp_is_independent_of_parent_and_branch(self):
        """The whole point: a row can be parentless and bare without being a top, and the
        two questions must give different answers."""
        store.create_agent(self.db, name="loner", role="lead")
        self.assertIsNone(store.get_agent(self.db, "loner")["parent"])
        self.assertIsNone(store.get_agent(self.db, "loner")["branch"])
        self.assertFalse(self.b.is_top("loner"))


class OnlyAHumanStartsATopTest(Fixture, unittest.TestCase):
    """`sb start` is refused for agents (DESIGN-TRUTH, confirmed 2026-08-11).

    At the CLI, because "who typed this" only exists there. The rule has two halves and
    they fail for different reasons: an agent this store knows is caught by `whoami`, and
    an agent it does not know — one standing in a clone, driving that clone's own store —
    is caught only by the Claude Code markers in its environment. The second half is the
    hole this closes: a clone IS its own main checkout, so the worktree refusal passes and
    three unwanted tops got made in one afternoon.
    """

    def _start(self, env: dict) -> tuple[int, str]:
        import argparse, contextlib, io, os  # noqa: E401
        from unittest import mock
        from switchboard import cli
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli._dispatch(argparse.Namespace(cmd="start", name=None, task=None,
                                                    json=False), self.b, self.db, self.h)
        return code, out.getvalue() + err.getvalue()

    def test_an_agent_this_store_knows_is_refused(self):
        self._top("top-a")
        store.create_agent(self.db, name="w1", role="worker", parent="top-a",
                           workspace="top-a", branch="top-a", pane_id="w1:p9")
        code, out = self._start({"HERDR_PANE_ID": "w1:p9"})
        self.assertEqual(code, 1)
        self.assertIn("only a human", out)
        # The refusal has to carry the alternative, or it is a wall.
        self.assertIn("sb delegate", out)
        self.assertEqual(self.h.started, [])

    def test_an_agent_in_a_clone_is_refused_though_the_store_has_no_row(self):
        """The clone. No agents at all — `whoami` says HUMAN and means it — so the only
        thing left saying otherwise is the session marker the harness sets."""
        code, out = self._start({"CLAUDE_CODE_SESSION_ID": "sess-from-a-clone"})
        self.assertEqual(code, 1)
        self.assertIn("only a human", out)
        self.assertEqual(self.h.started, [])

    def test_a_human_still_starts_one(self):
        """The entire point of the command, from both terminals a human has: a plain one,
        carrying nothing, and a herdr pane of their own, carrying a pane id no agent row
        claims. Neither has a session marker, so neither is mistaken for an agent."""
        for env in ({}, {"HERDR_PANE_ID": "w9:p9"}):
            with self.subTest(env=env):
                code, out = self._start(env)
                self.assertEqual(code, 0, out)
        self.assertEqual(len(self.h.started), 2)


class TopStampMigrationTest(unittest.TestCase):
    """The rows that predate the column. This is the migration risk, so it is proved.

    An unstamped row must not read as an ordinary agent — that would silently demote every
    real top, and its spawns would become tabs in the human's own checkout instead of
    forking. So the column is backfilled once, from the inference the code had been
    relying on implicitly all along.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "old.db"

    def tearDown(self):
        self.tmp.cleanup()

    def _old_store(self) -> sqlite3.Connection:
        """A store as it was before `is_top` existed."""
        d = store.connect(path=self.path)
        d.execute("ALTER TABLE agents DROP COLUMN is_top")
        d.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_hash', 'old')")
        d.commit()
        return d

    def test_pre_existing_tops_are_stamped_and_nobody_else_is(self):
        d = self._old_store()
        d.execute("INSERT INTO agents (name, role, state, workspace, created_at) "
                  "VALUES ('main', 'dispatcher', 'working', 'main', 1)")
        d.execute("INSERT INTO agents (name, parent, role, state, workspace, branch, "
                  "created_at) VALUES ('lead', 'main', 'lead', 'working', 'api', "
                  "'api', 1)")
        # Deliberately bare and NOT a top: the read-only agent whose shape used to be
        # indistinguishable from a top's, which is the bug this whole phase is about.
        d.execute("INSERT INTO agents (name, parent, role, state, workspace, created_at) "
                  "VALUES ('scout', 'lead', 'researcher', 'working', 'api', 1)")
        d.commit()
        d.close()

        db = store.connect(path=self.path)           # the migration runs here
        self.addCleanup(db.close)
        stamped = {r["name"]: r["is_top"]
                   for r in db.execute("SELECT name, is_top FROM agents")}
        self.assertEqual(stamped, {"main": 1, "lead": 0, "scout": 0})

    def test_a_backfilled_top_still_forks_its_children(self):
        """The behaviour the migration exists to preserve, not just the column value."""
        d = self._old_store()
        d.execute("INSERT INTO agents (name, role, state, workspace, cwd, pane_id, "
                  "created_at) VALUES ('main', 'dispatcher', 'working', 'main', ?, "
                  "'w1:p1', 1)", (str(self.path.parent),))
        d.commit()
        d.close()

        db = store.connect(path=self.path)
        self.addCleanup(db.close)
        h = FakeHerdr(self.path.parent / "worktrees")
        b = Broker(db, h, repo=self.path.parent)
        kid = b.delegate("t", role="worker", me="main")
        self.assertEqual(store.get_agent(db, kid)["branch"], kid)      # forked, not tabbed


# ---------------------------------------------------------------------------
# 5.2 — where a spawn lands
# ---------------------------------------------------------------------------


class WorktreeIsNotTopnessTest(Fixture, unittest.TestCase):
    """The phase-5 bug, pinned. A worktree-less agent that is NOT a top must not fork.

    Reproduced live before it was fixed: a non-root row
    with `branch IS NULL` delegated, and its child forked a brand-new space exactly as a
    top's would. `branch IS NULL` means "deliberately bare", which a read-only task deep in
    somebody's tree is too.
    """

    def _bare_non_top(self) -> str:
        """A read-only agent under a lead: no worktree of its own, and no stamp."""
        self._top()
        store.create_agent(self.db, name="lead", role="lead", parent="top",
                           workspace="api", branch="api", cwd=str(self.repo),
                           pane_id="w1:p2")
        store.create_agent(self.db, name="scout", role="lead", parent="lead",
                           workspace="api", pane_id="w1:p3")
        return "scout"

    def test_a_bare_non_top_tabs_rather_than_forking(self):
        scout = self._bare_non_top()
        self.assertFalse(self.b.has_worktree(scout))     # the fact the old rule read
        kid = self.b.delegate("t", role="worker", me=scout)
        self.assertEqual(self.h.calls_of("create_worktree"), [])
        self.assertEqual(store.get_agent(self.db, kid)["workspace"], "api")

    def test_a_top_with_the_same_shape_still_forks(self):
        """The control. Same `branch IS NULL`, opposite answer — which is only possible
        because the rule reads the stamp and not the branch."""
        kid = self.b.delegate("t", role="worker", me=self._top())
        self.assertEqual(self.h.calls_of("create_worktree"), [kid])

    def test_a_sub_orchestrators_whole_subtree_stays_in_one_space(self):
        """Three deep. DESIGN-TRUTH: "a sub-orchestrator a lead spawns is a tab in the
        lead's space, and its whole subtree stays in that one space"."""
        lead = self.b.delegate("t", role="lead", me=self._top())
        sub = self.b.delegate("t", role="lead", me=lead)
        kid = self.b.delegate("t", role="worker", me=sub)
        spaces = [store.get_agent(self.db, n)["workspace"] for n in (lead, sub, kid)]
        self.assertEqual(spaces, [lead, lead, lead])
        self.assertEqual(self.h.calls_of("create_worktree"), [lead])   # exactly one fork

    def test_a_caller_we_hold_no_row_for_still_forks(self):
        """Unknown provenance is not permission to write into whatever checkout `sb` ran
        in. Same answer as the human's, for the same reason."""
        self.assertTrue(self.b.mints_space("nobody"))
        self.assertTrue(self.b.mints_space(HUMAN))


# ---------------------------------------------------------------------------
# 5.3 — who may spawn
# ---------------------------------------------------------------------------


class BareAgentCannotDelegateTest(Fixture, unittest.TestCase):
    """DESIGN-TRUTH: "A bare agent's delegate is refused outright."

    Nothing enforced this before, and it was not hypothetical: a `worker`-role agent in the
    live store had spawned 17 children, orchestrators among them.
    """

    def test_a_worker_is_refused(self):
        store.create_agent(self.db, name="w", role="worker", parent=self._top(),
                           workspace="api", branch="api")
        with self.assertRaises(ValueError) as cm:
            self.b.delegate("t", role="worker", me="w")
        self.assertIn("does not spawn", str(cm.exception))
        self.assertIn("lead", str(cm.exception))          # and what CAN, by name

    def test_the_refusal_costs_no_row_and_no_pane(self):
        store.create_agent(self.db, name="w", role="worker", parent=self._top())
        with self.assertRaises(ValueError):
            self.b.delegate("t", role="worker", name="kid", me="w")
        self.assertIsNone(store.get_agent(self.db, "kid"))
        self.assertEqual(self.h.started, [])

    def test_a_lead_is_not_refused(self):
        self.assertTrue(self.b.delegate("t", role="worker", me=self._top()))

    def test_bareness_is_a_field_on_the_role_not_the_role_s_name(self):
        """Vocabulary is data — a repo that names its leaf role something else, or its
        orchestrating role something else, must still get the right answer. A check against
        the literal string `worker` breaks the moment either is renamed."""
        (self.repo / ".switchboard").mkdir(exist_ok=True)
        (self.repo / ".switchboard" / "roles.toml").write_text(
            "[foreman]\ndelegate = true\n[dogsbody]\ndelegate = false\n")
        b = Broker(self.db, self.h, repo=self.repo)     # reads the file just written
        store.create_agent(self.db, name="f", role="foreman", parent=self._top(),
                           workspace="api", branch="api", cwd=str(self.repo))
        store.create_agent(self.db, name="d", role="dogsbody", parent="f",
                           workspace="api", branch="api", cwd=str(self.repo))
        self.assertTrue(b.delegate("t", role="dogsbody", me="f"))
        with self.assertRaises(ValueError):
            b.delegate("t", role="dogsbody", me="d")

    def test_an_undefined_role_cannot_delegate(self):
        """A role nobody thought about is a leaf. Being wrong that way costs a refusal a
        person can lift; the other way costs a tree of agents nobody meant to exist."""
        store.create_agent(self.db, name="x", role="invented-yesterday",
                           parent=self._top())
        with self.assertRaises(ValueError):
            self.b.delegate("t", role="worker", me="x")

    def test_a_row_that_still_says_orchestrator_may_still_delegate(self):
        """The rename reaches the role table, never the rows already written. Every agent
        alive on the day this lands has `orchestrator` on its row, and the check above
        reads that string off the store — so without the alias resolving on a STORED role,
        and not only on a typed `--role`, the previous test is the one that would fire and
        the whole running fleet would lose the right to spawn."""
        store.create_agent(self.db, name="old", role="orchestrator",
                           parent=self._top(), workspace="api", branch="api",
                           cwd=str(self.repo))
        self.assertTrue(self.b.delegate("t", role="worker", me="old"))

    def test_delegating_with_the_retired_name_files_the_child_as_a_lead(self):
        """The alias resolves all the way, so the row says what the agent actually is: it
        is holding the lead prompt, and a row saying `orchestrator` would be a third answer
        to a question that already has two."""
        kid = self.b.delegate("t", role="orchestrator", me=self._top())
        self.assertEqual(store.get_agent(self.db, kid)["role"], "lead")


# ---------------------------------------------------------------------------
# 5.4 — the tree boundary
# ---------------------------------------------------------------------------


class TreeBoundaryTest(Fixture, unittest.TestCase):
    """DESIGN-TRUTH:175-181. "Siblings are not invisible to each other; any other top
    orchestrator's entire tree is invisible." And: "Only agents have the scope
    constraints" — the human crosses freely.

    The boundary is a TOP's whole tree, not the caller's descendants. `cleanup` scopes to
    `_descendants(me)`, which is a tighter rule that belongs to that one verb; copying it
    here would hide a sibling from a sibling.
    """

    def setUp(self):
        super().setUp()
        # Two trees, each two deep, so "sibling" and "cousin in another tree" are both
        # real positions rather than assertions about a pair of rows.
        for top in ("top-a", "top-b"):
            store.create_agent(self.db, name=top, role="lead", workspace=top,
                               cwd=str(self.repo), pane_id=f"w:{top}", is_top=True)
            for kid in ("1", "2"):
                store.create_agent(self.db, name=f"{top}-{kid}", role="worker",
                                   parent=top, workspace=top, branch=top,
                                   pane_id=f"w:{top}-{kid}")

    def test_the_top_of_a_tree_is_its_root_ancestor(self):
        self.assertEqual(self.b.top_of("top-a-1"), "top-a")
        self.assertEqual(self.b.top_of("top-a"), "top-a")

    def test_siblings_can_still_reach_each_other(self):
        self.assertEqual(len(self.b.tell(["top-a-2"], "hi", me="top-a-1")), 1)

    def test_another_tops_tree_cannot_be_told(self):
        with self.assertRaises(ValueError) as cm:
            self.b.tell(["top-b-1"], "hi", me="top-a-1")
        # Named as a boundary, not as a missing name: a workflow that quietly stops
        # crossing trees must not look like one that mistyped an agent.
        self.assertIn("another dispatcher's tree", str(cm.exception))

    def test_a_refused_tell_writes_no_message(self):
        with self.assertRaises(ValueError):
            self.b.tell(["top-b-1"], "hi", me="top-a-1")
        self.assertEqual(self.b.inbox(me="top-b-1", peek=True), [])

    def test_another_tops_tree_cannot_be_restored(self):
        store.update_agent(self.db, "top-b-1", session_id="sess-b1")
        with self.assertRaises(ValueError):
            self.b.restore("top-b-1", me="top-a-1")

    def test_the_human_crosses_freely(self):
        """The board is shared. Andrew is in no tree and is bounded by none of them."""
        self.assertTrue(self.b.same_tree(HUMAN, "top-a-1"))
        self.assertTrue(self.b.same_tree(HUMAN, "top-b-1"))
        self.assertEqual(len(self.b.tell(["top-b-1"], "hi", me=HUMAN)), 1)

    def test_agents_the_human_spawned_directly_are_one_group(self):
        """Parentless and UNSTAMPED is not a tree of one.

        `sb delegate` typed by a person makes a root that is not a top, and two of them are
        siblings in every sense that matters. The rule makes "another dispatcher's
        tree" invisible, and that is not what they are in. Treating each as its own tree
        cut a sibling off from a sibling — caught by the acceptance run's check 3, not by
        this file, which is why it is here now.
        """
        store.create_agent(self.db, name="solo-1", role="worker")
        store.create_agent(self.db, name="solo-2", role="worker")
        self.assertEqual(self.b.top_of("solo-1"), HUMAN)
        self.assertTrue(self.b.same_tree("solo-1", "solo-2"))
        self.assertEqual(len(self.b.tell(["solo-2"], "hi", me="solo-1")), 1)

    def test_the_humans_group_still_cannot_see_into_a_tops_tree(self):
        store.create_agent(self.db, name="solo-1", role="worker")
        self.assertFalse(self.b.same_tree("solo-1", "top-a-1"))
        self.assertFalse(self.b.same_tree("top-a-1", "solo-1"))
        self.assertNotIn("top-a", self.b.tree_of("solo-1"))

    def test_a_name_nothing_knows_is_not_refused_as_a_boundary(self):
        """A typo is a typo. "That is in another tree" is the wrong thing to tell somebody
        who mistyped, and whatever handled an unknown name before still handles it."""
        self.assertTrue(self.b.same_tree("top-a-1", "no-such-agent"))

    def test_a_cycle_in_the_parent_chain_does_not_spin(self):
        """The store has held one. A readout that hangs is worse than one that is wrong."""
        self.db.execute("UPDATE agents SET parent='top-a-1' WHERE name='top-a'")
        self.assertIn(self.b.top_of("top-a-1"), {"top-a", "top-a-1"})


class TreeBoundaryCliTest(Fixture, unittest.TestCase):
    """The four read verbs, at the CLI, where the caller's identity actually exists.

    `status`, `inspect` and `log` were global to everybody; `restore` took a bare name.
    Only `cleanup` was already scoped, and it is left alone.
    """

    def setUp(self):
        super().setUp()
        from switchboard import cli
        self.cli = cli
        for top in ("top-a", "top-b"):
            store.create_agent(self.db, name=top, role="lead", workspace=top,
                               cwd=str(self.repo), pane_id=f"w:{top}", is_top=True)
            store.create_agent(self.db, name=f"{top}-1", role="worker", parent=top,
                               workspace=top, branch=top, pane_id=f"w:{top}-1")

    def _run(self, ns, me_pane: str):
        import argparse, contextlib, io, os  # noqa: E401
        from unittest import mock
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"HERDR_PANE_ID": me_pane}, clear=True), \
                contextlib.redirect_stdout(buf):
            code = self.cli._dispatch(argparse.Namespace(**ns), self.b, self.db, self.h)
        return code, buf.getvalue()

    def test_status_shows_an_agent_its_own_tree_only(self):
        _, out = self._run(dict(cmd="status", json=False, live=False, needs_me=False,
                                mine=False, archived=True), "w:top-a-1")
        self.assertIn("top-a-1", out)
        self.assertNotIn("top-b", out)

    def test_status_shows_the_human_everything(self):
        _, out = self._run(dict(cmd="status", json=False, live=False, needs_me=False,
                                mine=False, archived=True), "")
        self.assertIn("top-a", out)
        self.assertIn("top-b", out)

    def test_inspect_is_refused_across_the_boundary(self):
        with self.assertRaises(ValueError):
            self._run(dict(cmd="inspect", json=False, name="top-b-1", n=5, events=3),
                      "w:top-a-1")

    def test_log_drops_another_trees_events(self):
        store.log_event(self.db, kind="delegate", agent="top-a-1")
        store.log_event(self.db, kind="delegate", agent="top-b-1")
        _, out = self._run(dict(cmd="log", json=False, agent=None, n=50), "w:top-a-1")
        self.assertIn("top-a-1", out)
        self.assertNotIn("top-b-1", out)


if __name__ == "__main__":
    unittest.main()
