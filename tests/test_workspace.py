"""Workspace tests — `sb workspace new`.

The load-bearing property is that a workspace is *shared*. One name means one worktree,
one herdr workspace and one lead agent, no matter how many agents or humans open it, in
what order, or at the same instant. Most of what follows exists to pin that down, because
the tempting implementations (fail if it exists, suffix the name, take a lock) all quietly
break it.

A fake herdr records what would have been called, so these run fast and spawn nothing.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import store  # noqa: E402
from switchboard.broker import HUMAN, Broker  # noqa: E402
from switchboard.herdr import Agent, HerdrError  # noqa: E402


class FakeHerdr:
    """A herdr that owns real workspace identity.

    Keyed by checkout path, as herdr is: one workspace per checkout. That is what makes
    "create twice" fail and "open" succeed, which is the whole behaviour the broker leans
    on. `worktree open --path` registers a checkout herdr had not seen before, so a repo
    that already exists on disk — including the primary one — can be attached to.
    """

    def __init__(self, root: Path):
        self.root = root
        self.checkouts: dict[str, dict] = {}     # checkout path -> facts
        self.opened: list[str] = []              # herdr workspace ids we handed back
        self.tabs: list[tuple[str, str]] = []    # (workspace_id, cwd)
        self.tab_panes: list[str] = []           # pane ids handed out by create_tab
        self.started: list[dict] = []
        self.prompts: list[tuple[str, str]] = []
        self.notifications: list[str] = []
        self.live: dict[str, Agent] = {}   # name -> what `agent list` reports
        self.closed: list[str] = []
        self.calls: list[str] = []
        self.splits: list[tuple[str, str, float]] = []   # (from_pane, direction, ratio)
        self.split_cwds: list[str] = []                  # where each split pane landed
        self.pane_prompts: list[tuple[str, str]] = []    # what was typed into a raw pane
        self.panes: set[str] = set()                     # every pane believed to exist
        self._n = 0
        self.lock = threading.Lock()

    # -- topology --------------------------------------------------------

    def _register(self, path: str, branch: str) -> dict:
        if path not in self.checkouts:
            self._n += 1
            self.checkouts[path] = {"id": f"w{self._n}", "branch": branch, "path": path,
                                    "root_pane": f"w{self._n}:p1"}
            self.panes.add(f"w{self._n}:p1")
        return self.checkouts[path]

    @staticmethod
    def _facts(wt: dict) -> dict:
        """The real dual shape, verified against `herdr worktree open`.

        Two worktree objects, two different key names: `workspace.worktree` is a
        `WorkspaceWorktreeInfo` and says `checkout_path`; the top-level one is a
        `WorktreeInfo` and says `path`, with no `checkout_path` anywhere in it. Faking
        `checkout_path` on the top-level object is what let broker.py read the path off the
        wrong object for 602 green tests.
        """
        return {"workspace": {"workspace_id": wt["id"], "label": wt["branch"],
                              "worktree": {"checkout_path": wt["path"],
                                           "repo_key": "/repo/.git",
                                           "repo_name": "repo",
                                           "repo_root": "/repo",
                                           "is_linked_worktree": True}},
                "worktree": {"path": wt["path"], "branch": wt["branch"],
                             "label": "repo", "is_bare": False, "is_detached": False,
                             "is_prunable": False, "is_linked_worktree": True,
                             "open_workspace_id": wt["id"]},
                "root_pane": {"pane_id": wt["root_pane"]},
                "tab": {"tab_id": wt["id"] + ":t1"}}

    def create_worktree(self, branch: str, *, base: str = "main",
                        cwd=None, label=None) -> dict:
        self.calls.append(f"create_worktree:{branch}")
        with self.lock:
            if any(w["branch"] == branch for w in self.checkouts.values()):
                # git refuses a second checkout of one branch, so herdr does too.
                raise HerdrError("worktree_exists", f"{branch} is already checked out")
            path = self.root / branch.replace("/", "-")
            path.mkdir(parents=True, exist_ok=True)
            wt = self._register(str(path), branch)
        self.opened.append(wt["id"])
        return self._facts(wt)

    def calls_of(self, kind):
        return [c.split(":", 1)[1] for c in self.calls if c.startswith(kind + ":")]

    def create_workspace(self, label, *, cwd=None, focus=False):
        if getattr(self, "fail_workspace_create", False):
            raise HerdrError("workspace_create_failed", "nope")
        self.calls.append(f"create_workspace:{label}")
        with self.lock:
            self._n = getattr(self, "_n", 100) + 1
            wid = f"w{self._n}"
        return {"workspace": {"workspace_id": wid, "label": label},
                "root_pane": {"pane_id": f"{wid}:p1"}}

    def close_workspace(self, workspace_id):
        pass

    def rename_workspace(self, workspace_id, label):
        for w in self.checkouts.values():
            if w["id"] == workspace_id:
                w["branch"] = label

    def open_worktree(self, *, path=None, branch=None, label=None, focus=False,
                      cwd=None) -> dict:
        self.calls.append(f"open_worktree:{branch or path}")
        with self.lock:
            if path:
                # herdr opens any checkout on disk, including one it has never seen and
                # including the repo's primary worktree.
                if not Path(path).is_dir():
                    raise HerdrError("worktree_not_found", f"no checkout at {path}")
                wt = self._register(str(path), label or branch or Path(path).name)
            else:
                wt = next((w for w in self.checkouts.values() if w["branch"] == branch),
                          None)
                if wt is None:
                    raise HerdrError("worktree_not_found", f"no worktree for {branch}")
        self.opened.append(wt["id"])
        return self._facts(wt)

    def create_tab(self, *, cwd=None, workspace=None, focus=False) -> str:
        with self.lock:
            self._n += 1
            pane = f"{workspace or 'w0'}:p{self._n}"
        self.tabs.append((workspace or "", cwd or ""))
        self.tab_panes.append(pane)
        self.panes.add(pane)
        return pane

    def close_pane(self, pane):
        self.closed.append(pane)

    def split_pane(self, pane, *, direction="right", ratio=0.38, cwd=None, focus=False):
        """`sb start` splits the orchestrator's pane to put the board beside it."""
        with self.lock:
            self._n += 1
            new = f"{pane}s{self._n}"
        self.splits.append((pane, direction, ratio))
        self.split_cwds.append(cwd or "")
        self.panes.add(new)
        return new

    def pane_ids(self):
        return set(self.panes)

    def prompt_pane(self, pane, text):
        self.pane_prompts.append((pane, text))

    # -- agents ----------------------------------------------------------

    def start_agent(self, name, pane, *, prompts=(), model_args=(), resume=None, **kw):
        with self.lock:
            if name in self.live:
                raise HerdrError("agent_name_taken", f"{name} is already running")
            a = Agent(name=name, pane_id=pane, terminal_id=f"term_{name}",
                      session_id=f"sess-{name}", raw={"cwd": kw.get("cwd", "")})
            self.live[name] = a
        self.started.append({"name": name, "pane": pane, "prompts": list(prompts),
                             "model_args": list(model_args), "resume": resume})
        return a

    def list_agents(self):
        return [self.live[n] for n in sorted(self.live)]

    def prompt(self, name, text): self.prompts.append((name, text))
    def notify(self, text): self.notifications.append(text)
    def focus(self, name): pass
    def report_state(self, pane, name, state, seq, **kw): pass
    def report_session(self, pane, name, sid, seq, **kw): pass
    def release_agent(self, pane, name, seq): pass


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.db = store.connect(path=self.repo / "state.db")
        self.h = FakeHerdr(self.repo / "worktrees")
        self.b = Broker(self.db, self.h, repo=self.repo)

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def _branches(self) -> list[str]:
        return sorted(w["branch"] for w in self.h.checkouts.values())

    def _git_repo(self) -> Path:
        """A real repo, for the parts that depend on what git actually reports."""
        import subprocess
        main = self.repo / "repo"; main.mkdir()
        run = lambda *a: subprocess.run(a, cwd=main, capture_output=True)   # noqa: E731
        run("git", "init", "-q", "-b", "main")
        run("git", "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-q", "--allow-empty", "-m", "x")
        return main

    # -- creating --------------------------------------------------------

    def test_new_creates_a_worktree_a_workspace_and_a_lead(self):
        r = self.b.workspace_new("api", me=HUMAN)
        self.assertEqual(r["workspace"], "api")
        self.assertTrue(r["created"])
        self.assertEqual(self._branches(), ["api"])                 # the git worktree
        self.assertTrue(r["workspace_id"])                          # the herdr workspace
        self.assertEqual(r["agent"], "api-lead")                    # the scoped orchestrator
        self.assertIn("api-lead", self.h.live)

    def test_the_lead_runs_inside_the_worktree_not_the_main_checkout(self):
        r = self.b.workspace_new("api", me=HUMAN)
        a = store.get_agent(self.db, "api-lead")
        self.assertTrue(r["path"])          # "" degrades to the main checkout downstream
        self.assertEqual(a["cwd"], r["path"])
        self.assertNotEqual(a["cwd"], str(self.repo))

    # -- reading the path off herdr's response ---------------------------
    #
    # herdr hands back two worktree objects with different key names. Reading the wrong one
    # yields "" — and "" never errors, it just quietly means "the main checkout" in
    # link_config, in the lead's system prompt, and in the recorded cwd the next open
    # trusts. These pin the read itself, below workspace_new.

    def test_the_path_is_read_off_the_workspace_scoped_worktree(self):
        """Both objects present — the real shape. The workspace-scoped one is the truth."""
        r = {"workspace": {"workspace_id": "w1",
                           "worktree": {"checkout_path": "/wt/api",
                                        "repo_root": "/repo",
                                        "is_linked_worktree": True}},
             "worktree": {"path": "/wt/api", "branch": "api", "is_bare": False},
             "root_pane": {"pane_id": "w1:p1"}}
        facts = self.b._workspace_facts("api", r, fresh=True)
        self.assertEqual(facts["path"], "/wt/api")
        self.assertEqual(facts["workspace_id"], "w1")
        self.assertEqual(facts["pane_id"], "w1:p1")

    def test_the_top_level_worktrees_path_key_is_accepted(self):
        """The top-level object says `path`, never `checkout_path` — take it when it is
        all we have, rather than reporting no worktree at all."""
        r = {"workspace": {"workspace_id": "w1"},
             "worktree": {"path": "/wt/api", "branch": "api"},
             "root_pane": {"pane_id": "w1:p1"}}
        self.assertEqual(self.b._workspace_facts("api", r, fresh=True)["path"], "/wt/api")

    def test_a_response_with_no_path_anywhere_raises(self):
        """Empty must never reach delegate: it is indistinguishable from the main
        checkout, and gets recorded as this workspace's path for every later open."""
        r = {"workspace": {"workspace_id": "w1"}, "worktree": {},
             "root_pane": {"pane_id": "w1:p1"}}
        with self.assertRaises(HerdrError) as e:
            self.b._workspace_facts("api", r, fresh=True)
        self.assertIn("workspace_no_path", str(e.exception))

    def test_a_worktree_carrying_no_path_is_not_opened_silently(self):
        """End to end: a herdr that answers with the wrong keys fails the open loudly
        instead of handing the lead the main checkout."""
        facts = FakeHerdr._facts
        self.h._facts = lambda wt: {**facts(wt),                      # type: ignore[method-assign]
                                    "workspace": {"workspace_id": wt["id"]},
                                    "worktree": {"branch": wt["branch"]}}
        with self.assertRaises(HerdrError) as e:
            self.b.workspace_new("api", me=HUMAN)
        self.assertIn("workspace_unavailable", str(e.exception))
        self.assertIn("workspace_no_path", str(e.exception))
        self.assertIsNone(store.get_agent(self.db, "api-lead"))

    def test_the_lead_takes_the_new_workspaces_root_pane(self):
        """A freshly created workspace already has an idle shell; do not waste a tab."""
        r = self.b.workspace_new("api", me=HUMAN)
        self.assertEqual(self.h.started[0]["pane"], r["pane_id"])
        self.assertEqual(self.h.tabs, [])

    def test_the_workspace_name_is_recorded_on_the_agent_row(self):
        self.b.workspace_new("api", me=HUMAN)
        self.assertEqual(store.get_agent(self.db, "api-lead")["workspace"], "api")

    def test_children_inherit_the_workspace_without_being_told(self):
        self.b.workspace_new("api", me=HUMAN)
        kid = self.b.delegate("do a thing", role="worker", me="api-lead")
        row = store.get_agent(self.db, kid)
        self.assertEqual(row["workspace"], "api")
        self.assertEqual(row["cwd"], store.get_agent(self.db, "api-lead")["cwd"])

    def test_a_childs_tab_is_placed_in_its_parents_workspace(self):
        r = self.b.workspace_new("api", me=HUMAN)
        self.b.delegate("t", role="worker", me="api-lead")
        self.assertEqual(self.h.tabs[-1][0], r["workspace_id"])

    def test_the_lead_is_told_it_is_sharing(self):
        """The agent must not assume it is alone in the checkout — others may be here."""
        self.b.workspace_new("api", me=HUMAN)
        joined = " ".join(self.h.started[0]["prompts"])
        self.assertIn("workspace 'api'", joined)
        self.assertIn("shared", joined)

    def test_prompts_stay_single_line(self):
        """herdr rejects multi-line agent args outright."""
        self.b.workspace_new("api", me=HUMAN)
        for p in self.h.started[0]["prompts"]:
            self.assertNotIn("\n", p)

    def test_the_lead_is_never_swept_away_by_cleanup(self):
        self.b.workspace_new("api", me=HUMAN)
        self.assertEqual(store.get_agent(self.db, "api-lead")["cleanup"], "keep")

    def test_a_task_is_delivered_to_a_new_lead(self):
        self.b.workspace_new("api", task="port the client", me=HUMAN)
        self.assertIn(("api-lead", "port the client"), self.h.prompts)

    def test_the_opener_becomes_the_parent(self):
        store.create_agent(self.db, name="main", role="main")
        self.b.workspace_new("api", me="main")
        self.assertEqual(store.get_agent(self.db, "api-lead")["parent"], "main")

    # -- no name means right here -----------------------------------------

    def test_no_name_opens_a_workspace_over_the_current_checkout(self):
        main = self._git_repo()
        r = Broker(self.db, self.h, repo=main).workspace_new(me=HUMAN)
        self.assertEqual(r["workspace"], "main")             # the branch it is on
        self.assertEqual(Path(r["path"]).resolve(), main.resolve())
        self.assertEqual([c for c in self.h.calls if c.startswith("create_")], [])

    def test_no_name_follows_the_branch_you_are_actually_on(self):
        import subprocess
        main = self._git_repo()
        subprocess.run(["git", "checkout", "-q", "-b", "release/9"], cwd=main,
                       capture_output=True)
        r = Broker(self.db, self.h, repo=main).workspace_new(me=HUMAN)
        self.assertEqual(r["workspace"], "release/9")
        self.assertEqual(r["agent"], "release-9-lead")

    def test_no_name_and_nowhere_to_infer_it_from_says_so(self):
        with self.assertRaises(ValueError) as cm:
            self.b.workspace_new(me=HUMAN)                   # a bare tmpdir
        self.assertIn("sb workspace new <name>", str(cm.exception))

    # -- reuse: the same name is always the same place ---------------------

    def test_reopening_reuses_the_worktree_and_the_workspace(self):
        first = self.b.workspace_new("api", me=HUMAN)
        second = self.b.workspace_new("api", me=HUMAN)
        self.assertFalse(second["created"])
        self.assertEqual(second["workspace_id"], first["workspace_id"])
        self.assertEqual(second["path"], first["path"])
        self.assertEqual(len(self.h.checkouts), 1)

    def test_reopening_reuses_the_lead_rather_than_starting_a_rival(self):
        self.b.workspace_new("api", me=HUMAN)
        second = self.b.workspace_new("api", me=HUMAN)
        self.assertEqual(second["agent"], "api-lead")
        self.assertEqual(len(self.h.started), 1)          # nothing was spawned twice

    def test_reopening_never_suffixes_the_name(self):
        """`api` must never quietly become `api-2` — that is a different place."""
        for _ in range(4):
            r = self.b.workspace_new("api", me=HUMAN)
            self.assertEqual(r["workspace"], "api")
            self.assertEqual(r["agent"], "api-lead")
        self.assertEqual(len(self.h.checkouts), 1)

    def test_reopening_does_not_error(self):
        self.b.workspace_new("api", me=HUMAN)
        self.b.workspace_new("api", me=HUMAN)       # would raise if reuse were an error

    def test_a_task_reaches_an_already_running_lead(self):
        self.b.workspace_new("api", me=HUMAN)
        self.b.workspace_new("api", task="also fix the tests", me=HUMAN)
        self.assertEqual(store.unread_for(self.db, "api-lead")[-1]["body"],
                         "also fix the tests")

    def test_a_second_agent_may_open_a_workspace_someone_else_is_in(self):
        """No ownership: a workspace opened by one agent is open to the next."""
        store.create_agent(self.db, name="one", role="orchestrator")
        store.create_agent(self.db, name="two", role="orchestrator")
        a = self.b.workspace_new("api", me="one")
        b = self.b.workspace_new("api", me="two")
        self.assertEqual(a["workspace_id"], b["workspace_id"])
        self.assertEqual(a["agent"], b["agent"])

    def test_a_human_may_open_a_workspace_an_agent_is_working_in(self):
        store.create_agent(self.db, name="one", role="orchestrator")
        agent_view = self.b.workspace_new("api", me="one")
        human_view = self.b.workspace_new("api", me=HUMAN)
        self.assertEqual(human_view["path"], agent_view["path"])
        self.assertFalse(human_view["created"])

    def test_a_separate_process_finds_the_same_workspace(self):
        """Two `sb` invocations share only the store; that has to be enough."""
        self.b.workspace_new("api", me=HUMAN)
        other = Broker(self.db, self.h, repo=self.repo)     # fresh process, empty cache
        again = other.workspace_new("api", me=HUMAN)
        self.assertEqual(len(self.h.checkouts), 1)
        self.assertFalse(again["created"])

    def test_a_forgotten_workspace_is_reattached_from_the_store(self):
        """A herdr restart loses live workspaces; our rows still know where it is."""
        first = self.b.workspace_new("api", me=HUMAN)
        self.h.live.clear()                                  # server restarted
        self.h.opened.clear()
        again = self.b.workspace_new("api", me=HUMAN)
        self.assertEqual(again["path"], first["path"])
        self.assertEqual(len(self.h.checkouts), 1)           # no second checkout
        self.assertIn(f"open_worktree:{first['path']}", self.h.calls)

    def test_an_already_checked_out_branch_is_attached_to_not_forked(self):
        """`sb workspace new main` lands on the main checkout you are standing in.

        git refuses a second checkout of one branch, so the only sane reading of a name
        that is already checked out somewhere is "take me there". No `sb/` prefix, no new
        branch, no error.
        """
        main = self._git_repo()
        b = Broker(self.db, self.h, repo=main)
        r = b.workspace_new("main", me=HUMAN)
        self.assertEqual(Path(r["path"]).resolve(), main.resolve())
        self.assertEqual(self._branches(), ["main"])
        self.assertNotIn("create_worktree:main", self.h.calls)   # never forked it
        self.assertEqual(r["agent"], "main-lead")

    def test_an_existing_branch_that_is_not_checked_out_is_checked_out(self):
        """The middle case: the branch exists, but nowhere on disk yet."""
        import subprocess
        main = self._git_repo()
        subprocess.run(["git", "branch", "spike"], cwd=main, capture_output=True)
        r = Broker(self.db, self.h, repo=main).workspace_new("spike", me=HUMAN)
        self.assertEqual(self._branches(), ["spike"])
        self.assertIn("create_worktree:spike", self.h.calls)     # herdr checks it out
        self.assertNotEqual(Path(r["path"]).resolve(), main.resolve())

    def test_the_base_only_matters_when_the_branch_is_new(self):
        main = self._git_repo()
        b = Broker(self.db, self.h, repo=main)
        b.workspace_new("fresh", base="main", me=HUMAN)
        self.assertIn("create_worktree:fresh", self.h.calls)
        self.h.calls.clear()
        b.workspace_new("main", me=HUMAN)                        # already checked out
        self.assertEqual([c for c in self.h.calls if c.startswith("create_")], [])

    def test_a_known_workspace_is_opened_before_it_is_created(self):
        """Reuse is the expected path, so it goes first — creation is the fallback."""
        self.b.workspace_new("api", me=HUMAN)
        self.h.calls.clear()
        self.b.workspace_new("api", me=HUMAN)
        self.assertTrue(self.h.calls[0].startswith("open_worktree"))

    def test_a_dead_lead_comes_back_with_its_context(self):
        self.b.workspace_new("api", me=HUMAN)
        self.h.live.clear()                                  # its pane was closed
        again = self.b.workspace_new("api", me=HUMAN)
        self.assertEqual(again["agent"], "api-lead")
        self.assertEqual(self.h.started[-1]["resume"], "sess-api-lead")
        self.assertEqual(self.h.tabs[-1][0], again["workspace_id"])   # back in its own

    # -- nothing is exclusive ---------------------------------------------

    def test_opening_takes_no_lock_of_any_kind(self):
        """Guard against a lock being 'helpfully' added later.

        No row, column, file or flag may mark a workspace as held: the whole point is
        that two agents and a human can be in it at once.
        """
        self.b.workspace_new("api", me=HUMAN)
        cols = {c[1] for c in self.db.execute("PRAGMA table_info(agents)")}
        self.assertFalse({"locked", "lock", "owner", "held_by", "in_use"} & cols)
        tables = {r[0] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(any("lock" in t for t in tables))
        self.assertEqual(list((self.repo / "worktrees").glob("**/*.lock")), [])

    def test_concurrent_openers_all_land_in_the_one_workspace(self):
        """The race the design has to survive: N openers, one name, no coordination."""
        results, errors = [], []
        start = threading.Barrier(6)

        def open_it():
            db = store.connect(path=self.repo / "state.db")   # its own connection
            try:
                start.wait(timeout=10)
                results.append(Broker(db, self.h, repo=self.repo)
                               .workspace_new("api", me=HUMAN))
            except Exception as e:                             # noqa: BLE001
                errors.append(e)
            finally:
                db.close()

        threads = [threading.Thread(target=open_it) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 6)
        self.assertEqual({r["workspace_id"] for r in results}, {results[0]["workspace_id"]})
        self.assertEqual({r["agent"] for r in results}, {"api-lead"})
        self.assertEqual(len(self.h.checkouts), 1)            # one checkout
        self.assertEqual(sum(1 for c in self.h.calls
                             if c.startswith("create_worktree")), 6)
        self.assertEqual(len(self.h.started), 1)              # one lead
        self.assertEqual(sum(r["created"] for r in results), 1)
        # every tab a loser opened was handed back — a contested workspace must not
        # slowly fill with the dead shells of openers that arrived a moment late
        in_use = self.h.started[0]["pane"]
        self.assertEqual(sorted(self.h.closed),
                         sorted(p for p in self.h.tab_panes if p != in_use))

    # -- `sb start` is a workspace open too --------------------------------

    def test_start_opens_a_workspace_over_the_checkout_you_ran_it_in(self):
        main = self._git_repo()
        b = Broker(self.db, self.h, repo=main)
        self.assertEqual(b.start(focus=False), "main")
        row = store.get_agent(self.db, "main")
        self.assertEqual(row["workspace"], "main")
        self.assertEqual(Path(row["cwd"]).resolve(), main.resolve())
        self.assertIsNone(row["parent"])                     # still a root
        self.assertEqual(row["cleanup"], "keep")

    def test_restarting_returns_to_the_running_orchestrator(self):
        b = Broker(self.db, self.h, repo=self._git_repo())
        b.start(focus=False)
        b.start(task="merge PR 41", focus=False)
        self.assertEqual(len(self.h.started), 1)             # nothing spawned twice
        self.assertEqual(store.unread_for(self.db, "main")[-1]["body"], "merge PR 41")

    def test_the_orchestrators_children_land_in_the_same_workspace(self):
        main = self._git_repo()
        b = Broker(self.db, self.h, repo=main)
        b.start(focus=False)
        kid = b.delegate("do a thing", role="worker", me="main")
        row = store.get_agent(self.db, kid)
        self.assertEqual(row["workspace"], "main")
        self.assertEqual(Path(row["cwd"]).resolve(), main.resolve())

    # -- the store is disposable; herdr's agents are not -------------------

    def test_adoption_does_not_invent_agents_herdr_does_not_have(self):
        b = Broker(self.db, self.h, repo=self._git_repo())
        b.start(focus=False)
        self.db.execute("DELETE FROM agents")
        self.db.commit()
        self.h.live.clear()                                  # herdr lost it too
        b.start(focus=False)
        self.assertEqual(len(self.h.started), 2)             # genuinely gone: respawn
        self.assertFalse(any(e["kind"] == "adopt"
                             for e in store.recent_events(self.db)))

    # -- failure modes ----------------------------------------------------

    def test_a_bad_name_is_refused_before_anything_is_created(self):
        for bad in ("", "has space", "-api", "/api", "a..b"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.b.workspace_new(bad, me=HUMAN)
        self.assertEqual(self.h.checkouts, {})

    def test_anything_git_would_accept_as_a_branch_is_a_valid_name(self):
        """The name IS the branch, so the branch rules are the only rules."""
        for ok in ("api", "feature/api-v2", "Fix-42", "1.2.x"):
            with self.subTest(ok=ok):
                self.assertEqual(self.b.workspace_new(ok, me=HUMAN)["workspace"], ok)
        self.assertEqual(self._branches(), sorted(("api", "feature/api-v2",
                                                   "Fix-42", "1.2.x")))

    def test_a_branch_name_herdr_cannot_use_still_gets_a_lead(self):
        """herdr agent names are `[a-z][a-z0-9_-]{0,31}`; branch names are not."""
        r = self.b.workspace_new("feature/API_v2", me=HUMAN)
        self.assertEqual(r["agent"], "feature-api_v2-lead")
        self.assertIn(r["agent"], self.h.live)
        self.assertEqual(store.get_agent(self.db, r["agent"])["workspace"],
                         "feature/API_v2")

    def test_a_long_branch_name_still_fits_herdrs_agent_name_limit(self):
        r = self.b.workspace_new("feature/" + "x" * 60, me=HUMAN)
        self.assertLessEqual(len(r["agent"]), 32)

    def test_a_workspace_that_can_neither_be_opened_nor_created_says_so(self):
        def refuse(*a, **k):
            raise HerdrError("disk_full", "no")
        self.h.create_worktree = refuse
        self.h.open_worktree = refuse
        with self.assertRaises(HerdrError) as cm:
            self.b.workspace_new("api", me=HUMAN)
        self.assertIn("api", str(cm.exception))
        self.assertIn("disk_full", str(cm.exception))

    def test_an_adapter_without_open_worktree_still_creates(self):
        """The reuse path degrades to a clear error; the create path is unaffected."""
        self.h.open_worktree = None                          # adapter predates `worktree open`
        self.assertTrue(self.b.workspace_new("api", me=HUMAN)["created"])
        with self.assertRaises(HerdrError) as cm:
            self.b.workspace_new("api", me=HUMAN)
        self.assertIn("open_worktree", str(cm.exception))

    def test_an_adapter_without_workspace_scoped_tabs_still_spawns(self):
        """Losing workspace placement is cosmetic; failing to spawn is not."""
        r = self.b.workspace_new("api", me=HUMAN)
        plain = lambda *, cwd=None, focus=False: "w9:p9"      # noqa: E731
        self.h.create_tab = plain
        kid = self.b.delegate("t", role="worker", me="api-lead")
        self.assertEqual(store.get_agent(self.db, kid)["workspace"], "api")
        self.assertEqual(store.get_agent(self.db, kid)["pane_id"], "w9:p9")
        self.assertTrue(r["workspace_id"])

    def test_delegating_outside_a_workspace_falls_back_to_the_callers_own(self):
        """An empty workspace id means "wherever herdr is FOCUSED", so a child would land
        in a stranger's workspace purely because something called focus recently. herdr
        injects the caller's own workspace into every pane; use that."""
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"HERDR_WORKSPACE_ID": "w1"}, clear=False):
            kid = self.b.delegate("t", role="worker", me=HUMAN)
        row = store.get_agent(self.db, kid)
        self.assertIsNone(row["workspace"])                  # no NAMED workspace
        self.assertEqual(row["cwd"], str(self.repo))
        self.assertEqual(self.h.tabs[-1][0], "w1")           # but placed where I am

    def test_with_no_workspace_anywhere_it_still_delegates(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {}, clear=True):
            kid = self.b.delegate("t", role="worker", me=HUMAN)
        self.assertEqual(self.h.tabs[-1][0], "")
        self.assertIsNotNone(store.get_agent(self.db, kid))

    # -- the board -------------------------------------------------------
    #
    # `sb start` opened one and `sb workspace new` did not, for no reason anybody chose.
    # The gate is the decided model: a board is the human's window onto agents somebody is
    # running, so it belongs to an orchestrator lead and to nobody else.

    def test_a_new_workspace_opens_a_board_beside_its_lead(self):
        self.b.workspace_new("api", me=HUMAN)
        lead = store.get_agent(self.db, "api-lead")
        self.assertEqual(len(self.h.splits), 1)
        from_pane, direction, _ratio = self.h.splits[0]
        self.assertEqual(from_pane, lead["pane_id"])        # split the lead's own pane
        self.assertEqual(direction, "right")
        self.assertIn("switchboard.board", self.h.pane_prompts[0][1])

    def test_the_board_reads_the_workspace_checkout_not_the_main_one(self):
        """A board pointed at the main checkout looks right and reports the wrong tree."""
        r = self.b.workspace_new("api", me=HUMAN)
        self.assertEqual(self.h.split_cwds, [r["path"]])
        self.assertNotEqual(r["path"], str(self.repo))

    def test_a_worker_lead_gets_no_board(self):
        """A plain worker forked into its own worktree runs nobody; a panel there is half
        a screen of empty view."""
        self.b.workspace_new("api", role="worker", me=HUMAN)
        self.assertIn("api-lead", self.h.live)              # the lead still spawned
        self.assertEqual(self.h.splits, [])
        self.assertEqual(self.h.pane_prompts, [])

    def test_no_board_declines_the_split(self):
        self.b.workspace_new("api", board=False, me=HUMAN)
        self.assertIn("api-lead", self.h.live)
        self.assertEqual(self.h.splits, [])
        self.assertEqual(self.h.pane_prompts, [])


class StartWorkspaceTest(WorkspaceTest):
    """`sb start` gives each top-level orchestrator its OWN workspace.

    Not a worktree (it does no writes) and not the repo's main workspace (several of them
    would pile into one place). Switching workspaces is one keystroke; hunting the right
    tab among everyone else's is not.
    """

    def test_start_creates_its_own_workspace(self):
        self.b.start(focus=False)
        self.assertIn("main", self.h.calls_of("create_workspace"))

    def test_each_new_orchestrator_gets_its_own_workspace(self):
        first = self.b.start(focus=False)
        second = self.b.start(new=True, focus=False)
        self.assertNotEqual(first, second)
        made = self.h.calls_of("create_workspace")
        self.assertEqual(made, [first, second])

    def test_returning_to_an_orchestrator_makes_no_new_workspace(self):
        self.b.start(focus=False)
        before = len(self.h.calls_of("create_workspace"))
        self.b.start(focus=False)                    # "take me back" is the default
        self.assertEqual(len(self.h.calls_of("create_workspace")), before)

    def test_start_creates_no_branch_and_no_worktree(self):
        """A top-level orchestrator does no writes, so it needs a place, not a checkout."""
        self.b.start(focus=False)
        self.assertEqual(self.h.calls_of("create_worktree"), [])

    def test_a_workspace_failure_still_starts_the_orchestrator(self):
        self.h.fail_workspace_create = True
        name = self.b.start(focus=False)
        self.assertIsNotNone(store.get_agent(self.db, name))

    # -- the board -------------------------------------------------------
    #
    # `open_beside` was once deleted as dead code because it was written a turn
    # before anything called it. These pin down that `sb start` calls it, so the
    # next reader can tell "unused" from "untested".

    def test_start_opens_the_board_beside_the_orchestrator(self):
        name = self.b.start(focus=False)
        agent = store.get_agent(self.db, name)
        self.assertEqual(len(self.h.splits), 1)
        from_pane, direction, _ratio = self.h.splits[0]
        self.assertEqual(from_pane, agent["pane_id"])       # split the orchestrator's own
        self.assertEqual(direction, "right")
        # and the new pane was told to run the board, not left as a bare shell
        self.assertEqual(len(self.h.pane_prompts), 1)
        self.assertIn("switchboard.board", self.h.pane_prompts[0][1])

    def test_no_board_declines_the_split(self):
        self.b.start(focus=False, board=False)
        self.assertEqual(self.h.splits, [])
        self.assertEqual(self.h.pane_prompts, [])

    def test_restarting_does_not_stack_a_second_board(self):
        name = self.b.start(focus=False)
        self.b.start(name=name, focus=False)
        self.b.start(name=name, focus=False)
        self.assertEqual(len(self.h.splits), 1, "one board per orchestrator, not three")

    def test_a_closed_board_is_reopened(self):
        name = self.b.start(focus=False)
        board_pane = self.h.splits[0][0] and self.h.pane_prompts[0][0]
        self.h.panes.discard(board_pane)                    # the human closed it
        self.b.start(name=name, focus=False)
        self.assertEqual(len(self.h.splits), 2)

    def test_a_board_failure_never_breaks_start(self):
        """The board is a view. `sb start` failing over one would be the worse bug."""
        def boom(*a, **kw):
            raise HerdrError("split_failed", "no panes left")
        self.h.split_pane = boom
        name = self.b.start(focus=False)
        self.assertIsNotNone(store.get_agent(self.db, name))

    def test_an_adapter_without_split_pane_never_breaks_start(self):
        """How this broke 13 tests the first time: AttributeError, not HerdrError."""
        def missing(*a, **kw):
            raise AttributeError("'Herdr' object has no attribute 'split_pane'")
        self.h.split_pane = missing
        name = self.b.start(focus=False)
        self.assertIsNotNone(store.get_agent(self.db, name))


class WorktreeIsAFactTest(WorkspaceTest):
    """"Does this agent have a worktree?" is read from the store, never from the name.

    The `workspace` column says a branch for a worktree space and an agent-ish label for a
    bare one, and nothing distinguishes the two. `branch` does: NULL means bare. The fork
    rule asks `Broker.has_worktree`, and the landmine below is what the conflation cost —
    looking up a bare space's herdr id used to fork it a git branch and a checkout.
    """

    def test_a_workspace_lead_records_the_branch_it_works_on(self):
        r = self.b.workspace_new("api", me=HUMAN)
        self.assertEqual(r["branch"], "api")
        self.assertEqual(store.get_agent(self.db, "api-lead")["branch"], "api")
        self.assertTrue(self.b.has_worktree("api-lead"))
        self.assertEqual(self.b.worktree_branch("api-lead"), "api")

    def test_children_inherit_the_branch_with_the_workspace(self):
        self.b.workspace_new("api", me=HUMAN)
        kid = self.b.delegate("t", role="worker", me="api-lead")
        grandkid = self.b.delegate("t", role="worker", me=kid)
        self.assertEqual(store.get_agent(self.db, kid)["branch"], "api")
        self.assertTrue(self.b.has_worktree(grandkid))

    def test_the_top_level_orchestrators_space_is_bare(self):
        """`sb start` lays a workspace over the main checkout and never forks. The row has
        to say so, or its children inherit a checkout that is the human's."""
        b = Broker(self.db, self.h, repo=self._git_repo())
        name = b.start(focus=False)
        self.assertIsNone(store.get_agent(self.db, name)["branch"])
        self.assertFalse(b.has_worktree(name))

    def test_nobody_and_the_human_have_no_worktree(self):
        self.assertFalse(self.b.has_worktree(HUMAN))
        self.assertFalse(self.b.has_worktree("never-existed"))

    def test_a_bare_space_is_not_mistaken_for_a_named_checkout(self):
        """The recorded cwd of a bare space is the main checkout — real, and not this
        workspace's. Reading it as one is what made a label look like a worktree."""
        store.create_agent(self.db, name="root", role="main", workspace="scratch",
                           cwd=str(self.repo))
        self.assertIsNone(self.b._recorded_path("scratch"))

    # -- the landmine ----------------------------------------------------

    def test_looking_up_a_bare_spaces_id_creates_no_branch_and_no_worktree(self):
        """`_workspace_id` fell through to `_attach_workspace`, whose create step runs
        `worktree create --branch <name>`. Merely resolving an id therefore forked a git
        branch and a checkout for a space that never had one."""
        store.create_agent(self.db, name="root", role="main", workspace="scratch",
                           cwd=str(self.repo))
        self.assertEqual(self.b._workspace_id("scratch"), "")
        self.assertEqual(self.h.calls, [])                   # herdr was not even asked
        self.assertEqual(self.h.checkouts, {})

    def test_a_childs_placement_never_forks_its_parents_bare_space(self):
        """End to end, through the path that actually reached it: the last-resort tab
        placement for a child whose parent's workspace id we never recorded."""
        import os
        from unittest import mock
        store.create_agent(self.db, name="root", role="main", workspace="scratch",
                           cwd=str(self.repo), pane_id="w1:p1")
        with mock.patch.dict(os.environ, {}, clear=True):
            kid = self.b.delegate("t", role="worker", me="root")
        self.assertEqual(self.h.calls_of("create_worktree"), [])
        self.assertIsNone(store.get_agent(self.db, kid)["branch"])
        self.assertEqual(store.get_agent(self.db, kid)["workspace"], "scratch")

    def test_an_unknown_name_is_looked_up_never_created(self):
        """No row at all is not permission to fork one. The open is tried — a herdr
        restart loses workspaces our store never knew — and failing it is harmless."""
        self.assertEqual(self.b._workspace_id("mystery"), "")
        self.assertEqual(self.h.calls_of("create_worktree"), [])
        self.assertEqual(self.h.checkouts, {})

    def test_a_bare_space_never_shadows_a_worktree_of_the_same_name(self):
        """Two spaces may share a name — that is what the split is for. A branch belongs
        to the workspace it was recorded in, and is not inherited by name."""
        self.b.workspace_new("api", me=HUMAN)                # worktree space 'api'
        store.create_agent(self.db, name="root", role="main", workspace="api",
                           cwd=str(self.repo))              # a bare row, same name
        self.assertIsNone(store.get_agent(self.db, "root")["branch"])
        kid = self.b.delegate("t", role="worker", me="root")
        self.assertIsNone(store.get_agent(self.db, kid)["branch"])

    def test_workspace_new_still_creates_the_worktree_it_is_asked_for(self):
        """The lookup stopped creating; the verb that means "make me one" must not."""
        self.b.workspace_new("api", me=HUMAN)
        self.assertEqual(self.h.calls_of("create_worktree"), ["api"])


class PluginsOnEverySpawnPathTest(unittest.TestCase):
    """A repo's plugin bindings reach EVERY spawn, not just `sb delegate`'s.

    While resolution lived in the CLI's `delegate` branch, `sb workspace new` and
    `sb start` called `Broker.delegate` straight past it, so a workspace lead and the
    top-level orchestrator silently missed the repo's every-agent bindings — a lead never
    received `own-files`. One resolution point in `Broker.delegate` is the fix.

    Not a subclass of `WorkspaceTest`: these need repo bindings on disk, and inheriting
    the setUp would re-run every workspace test with them.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.db = store.connect(path=self.repo / "state.db")
        self.h = FakeHerdr(self.repo / "worktrees")
        self.b = Broker(self.db, self.h, repo=self.repo)
        d = self.repo / ".switchboard" / "plugins"
        d.mkdir(parents=True)
        (d / "house-style").write_text("")     # a stray non-.md file must not register
        (d / "house-style.md").write_text("# House style\n\nkeep it short\n")
        (self.repo / ".switchboard" / "plugins.toml").write_text(
            'all = ["house-style"]\n\n[roles]\nworker = ["be exact"]\n'
        )

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def _prompts_for(self, name: str) -> list[str]:
        (started,) = [s for s in self.h.started if s["name"] == name]
        return started["prompts"]

    def test_delegate_resolves_the_repos_bindings(self):
        kid = self.b.delegate("t", role="worker", me=HUMAN)
        self.assertIn("keep it short", " ".join(self._prompts_for(kid)))

    def test_a_workspace_lead_gets_them_too(self):
        lead = self.b.workspace_new("api", me=HUMAN)["agent"]
        self.assertIn("keep it short", " ".join(self._prompts_for(lead)))

    def test_the_top_level_orchestrator_gets_them_too(self):
        top = self.b.start(focus=False, board=False)
        self.assertIn("keep it short", " ".join(self._prompts_for(top)))

    def test_every_spawn_path_resolves_the_same_bindings(self):
        """The property the fix is really about: one resolution point, not three."""
        kid = self.b.delegate("t", role="orchestrator", me=HUMAN)
        lead = self.b.workspace_new("api", me=HUMAN)["agent"]
        top = self.b.start(focus=False, board=False)
        plugins = [[p for p in self._prompts_for(n) if "keep it short" in p]
                   for n in (kid, lead, top)]
        self.assertEqual(plugins[0], plugins[1])
        self.assertEqual(plugins[1], plugins[2])
        self.assertEqual(len(plugins[0]), 1, "flattened to one line, and not duplicated")

    def test_a_per_role_binding_still_layers_on_top(self):
        """`all` then the role's own — the layering survives the move."""
        kid = self.b.delegate("t", role="worker", me=HUMAN)
        text = " ".join(self._prompts_for(kid))
        self.assertIn("keep it short", text)
        self.assertIn("be exact", text)

    def test_a_callers_own_with_is_appended_last(self):
        kid = self.b.delegate("t", role="worker", with_=["house-style", "and terse"],
                              me=HUMAN)
        prompts = self._prompts_for(kid)
        self.assertIn("and terse", prompts)
        self.assertEqual(len([p for p in prompts if "keep it short" in p]), 1,
                         "already bound for every agent; naming it again adds nothing")

    def test_a_plugin_that_cannot_flatten_names_the_plugin(self):
        """The CLI's error quality has to survive the move: this is what becomes an agent
        argument, so a plugin that flattens to something herdr rejects must say so."""
        (self.repo / ".switchboard" / "plugins" / "house-style.md").write_text("x" * 9000)
        with self.assertRaises(ValueError) as cm:
            self.b.delegate("t", role="worker", me=HUMAN)
        self.assertIn("plugin text", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
