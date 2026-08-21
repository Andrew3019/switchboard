"""Workspace tests — how a workspace is opened, joined, and left alone.

`sb workspace new` is gone. A workspace is minted by exactly one path — a TOP
orchestrator's `sb delegate` — and the child's name is the workspace's name, its branch
and its checkout. What survives the deletion is the property that verb existed for: a
workspace is *shared*. One name means one worktree, one herdr workspace and one branch, no
matter how many agents or humans are in it, in what order. Most of what follows exists to
pin that down, because the tempting implementations (fail if it exists, suffix the name,
take a lock) all quietly break it.

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

from switchboard import config, store  # noqa: E402
from switchboard.broker import HUMAN, Broker, ForkFailed  # noqa: E402
from switchboard.herdr import Agent, HerdrError  # noqa: E402



def _board_line(h) -> tuple[str, str]:
    """The board's own `pane run`, picked out by what it says rather than by position.

    Every spawn types a short command into its pane first and waits for the answer —
    `Broker._ready_pane`, which is what keeps a 12KB `agent start` out of a shell that is
    not reading yet — so the board is no longer the first thing in `pane_prompts`.
    """
    return next((pane, text) for pane, text in h.pane_prompts
                if "switchboard.board" in text)

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
        # A closed pane stops existing. Recording the call and leaving it in `panes`
        # would let a test claim a pane was closed while every reader still saw it.
        self.closed.append(pane)
        self.panes.discard(pane)

    def split_pane(self, pane, *, direction="right", ratio=0.66, cwd=None, focus=False):
        """Every spawn splits the agent's pane to put the board beside it. `ratio` is
        the share kept by the pane being split — see `Herdr.split_pane`."""
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

    def wait_output(self, pane_id, match, *, timeout_ms):
        """Every spawn proves its pane answers before `agent start` types into it —
        see `Broker._ready_pane`. Answering is the case this file is about."""
        return True

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
    def deliver(self, name, text, **kw): self.prompt(name, text)   # confirmed prompt
    def send_keys(self, name, *keys): self.calls.append(f"send_keys:{name}:{','.join(keys)}")
    def notify(self, text): self.notifications.append(text)
    def focus(self, name): pass
    def report_state(self, pane, name, state, seq, **kw): pass
    def report_session(self, pane, name, sid, seq, **kw): pass
    def release_agent(self, pane, name, seq): pass
    def check(self, **kw): pass


class Fixture:
    """Setup shared by the classes below.

    Deliberately not a `TestCase`: subclassing `WorkspaceTest` to borrow its fixture
    re-ran every one of its ~70 tests once per subclass, eight times over — 490 test runs
    that proved nothing the first run had not.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.db = store.connect(path=self.repo / "state.db")
        self.h = FakeHerdr(self.repo / "worktrees")
        self.b = Broker(self.db, self.h, repo=self.repo)

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def _root(self, name: str = "root", *, cwd=None) -> str:
        """A top orchestrator's space: a herdr workspace over the main checkout, no branch
        of its own, STAMPED. What `sb start` produces — and, since `sb workspace new` was
        deleted, the only caller whose spawn mints a workspace."""
        if store.get_agent(self.db, name) is None:
            store.create_agent(self.db, name=name, role="lead",
                               workspace="scratch", cwd=str(cwd or self.repo),
                               pane_id="w1:p1", is_top=True)
        return name

    def _open(self, name: str = "api", *, b=None, me=None, role: str = "lead",
              task: str = "t", **kw) -> dict:
        """Open the workspace `name` the one way left: a top delegates, and the child's
        NAME is the workspace, the branch and the checkout. Returns the facts the deleted
        verb used to hand back, read off the child's own row."""
        b = b or self.b
        agent = b.delegate(task, role=role, name=name,
                           me=me or self._root(cwd=b.repo), **kw)
        row = store.get_agent(self.db, agent)
        return {"workspace": row["workspace"], "branch": row["branch"],
                "workspace_id": row["workspace_id"], "path": row["cwd"],
                "agent": agent, "pane_id": row["pane_id"]}

    def _prompts_of(self, name: str) -> str:
        (started,) = [s for s in self.h.started if s["name"] == name]
        return " ".join(started["prompts"])

    def _fork_event(self) -> dict:
        """What `_fork_for` recorded about the most recent fork."""
        import json
        e = next(e for e in store.recent_events(self.db) if e["kind"] == "fork")
        return json.loads(e["payload"])

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

class WorkspaceTest(Fixture, unittest.TestCase):
    # -- creating --------------------------------------------------------

    def test_a_tops_delegate_creates_a_worktree_a_workspace_and_a_lead(self):
        """The one path that opens a workspace, now that the verb is gone."""
        r = self._open("api")
        self.assertEqual(r["workspace"], "api")
        self.assertEqual(self._branches(), ["api"])                 # the git worktree
        self.assertTrue(r["workspace_id"])                          # the herdr workspace
        self.assertEqual(r["agent"], "api")                         # the scoped orchestrator
        self.assertIn("api", self.h.live)

    def test_the_lead_runs_inside_the_worktree_not_the_main_checkout(self):
        r = self._open("api")
        self.assertTrue(r["path"])          # "" degrades to the main checkout downstream
        self.assertNotEqual(r["path"], str(self.repo))

    def test_no_verb_opens_one_directly_any_more(self):
        """DESIGN-TRUTH: "`sb workspace new` is deleted, provided the other commands cover
        it fully". Both halves go — the broker method and the subcommand — so a second way
        to mint a space cannot quietly come back."""
        from switchboard.cli import build_parser
        self.assertFalse(hasattr(self.b, "workspace_new"))
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["workspace", "new", "api"])

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
        """End to end: a herdr that answers with the wrong keys fails the fork loudly
        instead of handing the agent the main checkout."""
        facts = FakeHerdr._facts
        self.h._facts = lambda wt: {**facts(wt),                      # type: ignore[method-assign]
                                    "workspace": {"workspace_id": wt["id"]},
                                    "worktree": {"branch": wt["branch"]}}
        with self.assertRaises(ForkFailed) as e:
            self._open("api")
        self.assertIn("workspace_no_path", str(e.exception))
        self.assertIsNone(store.get_agent(self.db, "api"))

    def test_children_inherit_the_workspace_without_being_told(self):
        lead = self._open("api")
        kid = self.b.delegate("do a thing", topic="t", role="worker", me=lead["agent"])
        row = store.get_agent(self.db, kid)
        self.assertEqual(row["workspace"], "api")
        self.assertEqual(row["cwd"], lead["path"])

    def test_a_childs_tab_is_placed_in_its_parents_workspace(self):
        r = self._open("api")
        self.b.delegate("t", topic="t", role="worker", me="api")
        self.assertEqual(self.h.tabs[-1][0], r["workspace_id"])

    def test_the_lead_is_told_it_is_sharing(self):
        """The agent must not assume it is alone in the checkout — others may be here."""
        self._open("api")
        prompts = self._prompts_of("api")
        self.assertIn("workspace 'api'", prompts)
        self.assertIn("shared", prompts)

    def test_a_lead_is_written_with_no_disposition_of_its_own(self):
        """It used to be written `keep`. Nothing writes that column any more — what stays
        open is the orchestrator's run-time call, not a value stamped at spawn."""
        self._open("api")
        self.assertEqual(store.get_agent(self.db, "api")["cleanup"], "close")

    def test_the_opener_becomes_the_parent(self):
        self._open("api", me=self._root("main"))
        self.assertEqual(store.get_agent(self.db, "api")["parent"], "main")

    # -- attaching: the same name is always the same place -----------------
    #
    # `_attach_workspace` is what both remaining doors go through — a top's fork, and
    # `--workspace` joining one — so what it does with a name is pinned here directly
    # rather than through a verb. The name IS the branch, and a branch that already exists
    # is somewhere to go, not a collision to route around.

    def test_an_already_checked_out_branch_is_attached_to_not_forked(self):
        """A name already checked out somewhere lands on that checkout.

        git refuses a second checkout of one branch, so the only sane reading of such a
        name is "take me there". No `sb/` prefix, no new branch, no error.
        """
        main = self._git_repo()
        ws = Broker(self.db, self.h, repo=main)._attach_workspace("main")
        self.assertEqual(Path(ws["path"]).resolve(), main.resolve())
        self.assertEqual(self._branches(), ["main"])
        self.assertNotIn("create_worktree:main", self.h.calls)   # never forked it

    def test_an_existing_branch_that_is_not_checked_out_is_checked_out(self):
        """The middle case: the branch exists, but nowhere on disk yet."""
        import subprocess
        main = self._git_repo()
        subprocess.run(["git", "branch", "spike"], cwd=main, capture_output=True)
        ws = Broker(self.db, self.h, repo=main)._attach_workspace("spike")
        self.assertEqual(self._branches(), ["spike"])
        self.assertIn("create_worktree:spike", self.h.calls)     # herdr checks it out
        self.assertNotEqual(Path(ws["path"]).resolve(), main.resolve())

    def test_the_base_only_matters_when_the_branch_is_new(self):
        main = self._git_repo()
        b = Broker(self.db, self.h, repo=main)
        b._attach_workspace("fresh", base="main")
        self.assertIn("create_worktree:fresh", self.h.calls)
        self.h.calls.clear()
        b._attach_workspace("main")                              # already checked out
        self.assertEqual([c for c in self.h.calls if c.startswith("create_")], [])

    def test_a_forgotten_workspace_is_reattached_from_the_store(self):
        """A herdr restart loses live workspaces; our rows still know where it is."""
        first = self._open("api")
        self.h.opened.clear()                                    # server restarted
        again = self.b._attach_workspace("api")
        self.assertEqual(again["path"], first["path"])
        self.assertEqual(len(self.h.checkouts), 1)               # no second checkout
        self.assertIn(f"open_worktree:{first['path']}", self.h.calls)

    # -- nothing is exclusive ---------------------------------------------

    def test_opening_takes_no_lock_of_any_kind(self):
        """Guard against a lock being 'helpfully' added later.

        No row, column, file or flag may mark a workspace as held: the whole point is
        that two agents and a human can be in it at once.
        """
        self._open("api")
        cols = {c[1] for c in self.db.execute("PRAGMA table_info(agents)")}
        self.assertFalse({"locked", "lock", "owner", "held_by", "in_use"} & cols)
        tables = {r[0] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(any("lock" in t for t in tables))
        self.assertEqual(list((self.repo / "worktrees").glob("**/*.lock")), [])

    def test_concurrent_spawners_of_one_name_leave_exactly_one_agent(self):
        """The race the design still has to survive, in the shape the deletion leaves it.

        `sb workspace new` answered a collision by JOINING — same name, same lead, every
        caller served. A fork cannot: the name is a branch, and two agents cannot both
        own it. So the surviving guarantee is narrower and has to be pinned as such —
        one winner, the losers REFUSED by name (a caller error `sb` reports as one), and
        never the bare `sqlite3.IntegrityError` out of the middle of a spawn that the
        primary key used to produce.
        """
        from switchboard.broker import AgentNameTaken
        self._root()
        won, refused, other = [], [], []
        start = threading.Barrier(6)

        def spawn():
            db = store.connect(path=self.repo / "state.db")   # its own connection
            try:
                start.wait(timeout=10)
                won.append(Broker(db, self.h, repo=self.repo)
                           .delegate("t", role="worker", name="api", me="root"))
            except AgentNameTaken as e:
                refused.append(e)
            except Exception as e:                             # noqa: BLE001
                other.append(e)
            finally:
                db.close()

        threads = [threading.Thread(target=spawn) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(other, [])
        self.assertEqual(won, ["api"])                        # exactly one winner
        self.assertEqual(len(refused), 5)
        self.assertEqual(len(self.h.started), 1)              # and one agent started

    # -- `sb start` is a workspace open too --------------------------------

    def test_start_opens_a_workspace_over_the_checkout_you_ran_it_in(self):
        main = self._git_repo()
        b = Broker(self.db, self.h, repo=main)
        self.assertEqual(b.start(), "main")
        row = store.get_agent(self.db, "main")
        self.assertEqual(row["workspace"], "main")
        self.assertEqual(Path(row["cwd"]).resolve(), main.resolve())
        self.assertIsNone(row["parent"])                     # still a root

    def test_restarting_opens_another_workspace_rather_than_returning(self):
        """Unnamed, `sb start` is only ever the start of something — a second line of
        work in a second bare space over the same checkout. Naming one is how you go
        back to it, and that is what the test below pins."""
        b = Broker(self.db, self.h, repo=self._git_repo())
        first = b.start()
        second = b.start(task="merge PR 41")
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.h.started), 2)
        self.assertEqual(store.unread_for(self.db, first), [])   # left entirely alone

    def test_naming_the_running_orchestrator_returns_to_it(self):
        b = Broker(self.db, self.h, repo=self._git_repo())
        name = b.start()
        b.start(name=name, task="merge PR 41")
        self.assertEqual(len(self.h.started), 1)             # nothing spawned twice
        self.assertEqual(store.unread_for(self.db, name)[-1]["body"], "merge PR 41")

    def test_the_orchestrators_children_never_land_in_the_main_checkout(self):
        """The fork rule, at the depth that matters most.

        This test used to assert the opposite — that a root's child shared its bare space
        over the main checkout — which is exactly the behaviour the decided model exists
        to end: everything below the root writes, and the root's space is the human's own
        checkout.
        """
        main = self._git_repo()
        b = Broker(self.db, self.h, repo=main)
        b.start()
        kid = b.delegate("do a thing", topic="t", role="worker", me="main")
        row = store.get_agent(self.db, kid)
        self.assertEqual(row["workspace"], kid)              # a tree of its own
        self.assertEqual(row["branch"], kid)
        self.assertNotEqual(Path(row["cwd"]).resolve(), main.resolve())

    # -- the store is disposable; herdr's agents are not -------------------

    def test_adoption_does_not_invent_agents_herdr_does_not_have(self):
        b = Broker(self.db, self.h, repo=self._git_repo())
        b.start()
        self.db.execute("DELETE FROM agents")
        self.db.commit()
        self.h.live.clear()                                  # herdr lost it too
        b.start()
        self.assertEqual(len(self.h.started), 2)             # genuinely gone: respawn
        self.assertFalse(any(e["kind"] == "adopt"
                             for e in store.recent_events(self.db)))

    # -- failure modes ----------------------------------------------------

    def test_a_hostile_topic_still_composes_a_name_git_and_herdr_accept(self):
        """The name is the agent's AND the branch's, and since `<role>-<topic>` naming the
        half a caller supplies is prose. So the guarantee moved rather than went: `--name`
        is no longer checked as a name (it is not one), and `Broker._compose_name` slugs
        whatever arrives into something both herdr and git take.

        An EMPTY topic is the one that is still refused, and by the broker: a spawn with
        nothing to be named for is the case the composition exists to end."""
        from switchboard import validate
        for hostile in ("has space", "-api", "/api", "a..b", "API/../etc", "ünïcode"):
            with self.subTest(hostile=hostile):
                got = self.b._compose_name("worker", hostile)
                self.assertEqual(validate.agent_name(got), got)
                self.assertEqual(validate.ref_name(got), got)      # it is also the branch
        with self.assertRaises(ValueError):
            self.b._compose_name("worker", "   ")
        self.assertEqual(self.h.checkouts, {})

    def test_a_workspace_that_can_neither_be_opened_nor_created_says_so(self):
        def refuse(*a, **k):
            raise HerdrError("disk_full", "no")
        self.h.create_worktree = refuse
        self.h.open_worktree = refuse
        with self.assertRaises(ForkFailed) as cm:
            self._open("api")
        self.assertIn("api", str(cm.exception))
        self.assertIn("disk_full", str(cm.exception))

    def test_an_adapter_without_open_worktree_still_creates(self):
        """The reattach path degrades to a clear error; the create path is unaffected."""
        self.h.open_worktree = None                          # adapter predates `worktree open`
        self.assertEqual(self._open("api")["workspace"], "api")
        self.h.opened.clear()
        with self.assertRaises(HerdrError) as cm:
            self.b._attach_workspace("api")
        self.assertIn("open_worktree", str(cm.exception))

    def test_an_adapter_without_workspace_scoped_tabs_still_spawns(self):
        """Losing workspace placement is cosmetic; failing to spawn is not."""
        r = self._open("api")
        plain = lambda *, cwd=None, focus=False: "w9:p9"      # noqa: E731
        self.h.create_tab = plain
        kid = self.b.delegate("t", topic="t", role="worker", me="api")
        self.assertEqual(store.get_agent(self.db, kid)["workspace"], "api")
        self.assertEqual(store.get_agent(self.db, kid)["pane_id"], "w9:p9")
        self.assertTrue(r["workspace_id"])

    def test_delegating_with_no_recorded_workspace_id_falls_back_to_the_callers_own(self):
        """An empty workspace id means "wherever herdr is FOCUSED", so a child would land
        in a stranger's workspace purely because something called focus recently. herdr
        injects the caller's own workspace into every pane; use that.

        The parent here has a worktree, so nothing forks and placement is the only thing
        under test — a parent WITHOUT one now forks, which is its own answer to "where
        does this child go".
        """
        import os
        from unittest import mock
        store.create_agent(self.db, name="lead", role="lead", workspace="api",
                           branch="api", cwd=str(self.repo))      # no workspace_id
        with mock.patch.dict(os.environ, {"HERDR_WORKSPACE_ID": "w1"}, clear=False):
            kid = self.b.delegate("t", topic="t", role="worker", me="lead")
        row = store.get_agent(self.db, kid)
        self.assertEqual(row["workspace"], "api")            # inherited, not forked
        self.assertEqual(row["cwd"], str(self.repo))
        self.assertEqual(self.h.tabs[-1][0], "w1")           # but placed where I am

    def test_a_fork_that_cannot_happen_refuses_the_spawn_and_says_so(self):
        """A fork that fails takes the spawn down with it, deliberately.

        The parent has no worktree, so the rule says fork — and this herdr cannot make
        one. It used to degrade: the child spawned in its parent's space instead, with a
        `fork_failed` row as the only trace. For a child of the top orchestrator that
        space is Andrew's own checkout, so the degraded child wrote its work into the one
        place everybody's uncommitted work lives, on somebody else's branch. Nothing is
        spawned now, and the caller is told why — DESIGN-TRUTH: "A fork that fails refuses
        the spawn and tells the parent. It never falls back to Andrew's own checkout."
        """
        import os
        from unittest import mock
        self.h.create_worktree = None                        # an adapter that cannot fork
        self.h.open_worktree = None
        before = {a["name"] for a in store.live_agents(self.db)}
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ForkFailed) as cm:
                self.b.delegate("t", topic="t", role="worker", me=HUMAN)
        self.assertIn("worktree of its own", str(cm.exception))
        self.assertIn(str(self.repo), str(cm.exception))      # the checkout it refused
        self.assertEqual({a["name"] for a in store.live_agents(self.db)}, before)
        self.assertEqual(self.h.started, [])                  # and nothing was started
        self.assertTrue(any(e["kind"] == "fork_failed"
                            for e in store.recent_events(self.db)))

    # -- the board -------------------------------------------------------
    #
    # `sb start` opened one and nothing else did. The decided model now is that EVERY
    # spawned agent opens with one, orchestrator or worker — which is affordable because
    # the board is the small pane, not half the screen. `--no-board` still declines it.

    def test_a_new_workspace_opens_a_board_beside_its_lead(self):
        self._open("api")
        lead = store.get_agent(self.db, "api")
        self.assertEqual(len(self.h.splits), 1)
        from_pane, direction, _ratio = self.h.splits[0]
        self.assertEqual(from_pane, lead["pane_id"])        # split the lead's own pane
        self.assertEqual(direction, "right")
        self.assertIn("switchboard.board", _board_line(self.h)[1])

    def test_the_board_reads_the_workspace_checkout_not_the_main_one(self):
        """A board pointed at the main checkout looks right and reports the wrong tree."""
        r = self._open("api")
        self.assertEqual(self.h.split_cwds, [r["path"]])
        self.assertNotEqual(r["path"], str(self.repo))

    def test_a_delegated_child_opens_a_board_beside_itself(self):
        """`sb delegate` used to hand out a bare tab. Every spawn goes through
        `delegate`, so this is where the board is opened for all of them."""
        kid = self.b.delegate("t", topic="t", role="worker", me=HUMAN)
        pane = store.get_agent(self.db, kid)["pane_id"]
        self.assertIn((pane, "right"), [(p, d) for p, d, _r in self.h.splits])
        self.assertTrue(any("switchboard.board" in t for _p, t in self.h.pane_prompts))

    def test_the_board_is_the_small_pane(self):
        """herdr's ratio is the share kept by the pane being SPLIT, so the agent's own
        session keeps the majority and the board gets what is left."""
        self.b.delegate("t", topic="t", role="worker", me=HUMAN)
        _pane, _dir, ratio = self.h.splits[0]
        self.assertGreater(ratio, 0.5, "the agent's session must be the larger pane")
        self.assertLess(ratio, 0.8)                         # and the board still readable

    def test_a_delegated_child_still_spawns_when_the_split_fails(self):
        """The board is a view; a spawn must not fail because one would not open."""
        def boom(*a, **kw):
            raise HerdrError("split_failed", "no panes left")
        self.h.split_pane = boom
        kid = self.b.delegate("t", topic="t", role="worker", me=HUMAN)
        self.assertIn(kid, self.h.live)
        self.assertTrue(any(e["kind"] == "board_open_failed"
                            for e in store.recent_events(self.db)))

    def test_the_board_cannot_be_declined(self):
        """`--no-board` is gone: every sb-made view is split with the board."""
        self._open("api")
        self.assertIn("api", self.h.live)
        self.assertEqual(len(self.h.splits), 1)
        self.assertIn("switchboard.board", _board_line(self.h)[1])


class StartWorkspaceTest(Fixture, unittest.TestCase):
    """`sb start` gives each top-level orchestrator its OWN workspace.

    Not a worktree (it does no writes) and not the repo's main workspace (several of them
    would pile into one place). Switching workspaces is one keystroke; hunting the right
    tab among everyone else's is not.
    """

    def test_start_creates_its_own_workspace(self):
        self.b.start()
        self.assertIn("main", self.h.calls_of("create_workspace"))

    def test_each_start_gets_its_own_workspace(self):
        first = self.b.start()
        second = self.b.start()
        self.assertNotEqual(first, second)
        made = self.h.calls_of("create_workspace")
        self.assertEqual(made, [first, second])

    def test_returning_to_an_orchestrator_by_name_makes_no_new_workspace(self):
        name = self.b.start()
        before = len(self.h.calls_of("create_workspace"))
        self.b.start(name=name)
        self.assertEqual(len(self.h.calls_of("create_workspace")), before)

    def test_start_creates_no_branch_and_no_worktree(self):
        """A top-level orchestrator does no writes, so it needs a place, not a checkout."""
        self.b.start()
        self.assertEqual(self.h.calls_of("create_worktree"), [])

    def test_a_workspace_failure_still_starts_the_orchestrator(self):
        self.h.fail_workspace_create = True
        name = self.b.start()
        self.assertIsNotNone(store.get_agent(self.db, name))

    # -- the board -------------------------------------------------------
    #
    # `open_beside` was once deleted as dead code because it was written a turn
    # before anything called it. These pin down that `sb start` calls it, so the
    # next reader can tell "unused" from "untested".

    def test_start_opens_the_board_beside_the_orchestrator(self):
        name = self.b.start()
        agent = store.get_agent(self.db, name)
        self.assertEqual(len(self.h.splits), 1)
        from_pane, direction, _ratio = self.h.splits[0]
        self.assertEqual(from_pane, agent["pane_id"])       # split the orchestrator's own
        self.assertEqual(direction, "right")
        # and the new pane was told to run the board, not left as a bare shell
        self.assertEqual(sum("switchboard.board" in t for _p, t in self.h.pane_prompts), 1)
        self.assertIn("switchboard.board", _board_line(self.h)[1])

    def test_the_board_cannot_be_declined(self):
        """`--no-board` is gone: every sb-made view is split with the board."""
        self.b.start()
        self.assertEqual(len(self.h.splits), 1)
        self.assertIn("switchboard.board", _board_line(self.h)[1])

    def test_a_delegated_child_s_board_is_the_size_sb_start_s_is(self):
        """One board, one width. It used to be two constants picked by a `top=` flag,
        so the same view came out one size from `sb start` and another from `delegate`."""
        from switchboard import board as board_mod
        self.b.start()
        _pane, _dir, top_ratio = self.h.splits[0]
        self.b.delegate("t", topic="t", role="worker", me=HUMAN)
        _pane, _dir, kid_ratio = self.h.splits[1]
        # herdr's ratio is what the SPLIT pane keeps, so a wider board is a smaller one.
        self.assertAlmostEqual(top_ratio, 1 - board_mod.BOARD_SHARE)
        self.assertAlmostEqual(kid_ratio, top_ratio)

    def test_the_board_is_still_the_side_panel(self):
        """Roomier, not the main event: the agent's own session keeps the majority."""
        from switchboard import board as board_mod
        self.assertLess(board_mod.BOARD_SHARE, 0.5)

    def test_a_closed_board_is_reopened(self):
        name = self.b.start()
        board_pane = self.h.splits[0][0] and _board_line(self.h)[0]
        self.h.panes.discard(board_pane)                    # the human closed it
        self.b.start(name=name)
        self.assertEqual(len(self.h.splits), 2)

class ClosingTakesTheBoardWithItTest(Fixture, unittest.TestCase):
    """A board opened beside an agent is closed when that agent is.

    Every spawn opens one now, so a close that took only the agent's own pane left an
    empty tab behind once per agent — observed, and closed by hand.
    """

    def _finished_kid(self) -> tuple[str, str, str]:
        """A closable child. -> (name, its board's pane, its own pane)"""
        self._open("api")
        kid = self.b.delegate("t", topic="t", role="worker", me="api")
        store.set_state(self.db, kid, "done")
        agent_pane = store.get_agent(self.db, kid)["pane_id"]
        return kid, self._board_pane(kid), agent_pane

    def _board_pane(self, name):
        row = self.db.execute("SELECT value FROM meta WHERE key=?",
                              (f"board_pane:{name}",)).fetchone()
        return row["value"] if row else None

    def test_closing_an_agent_closes_its_board(self):
        kid, board, agent_pane = self._finished_kid()
        self.assertIsNotNone(board)
        self.assertEqual(self.b.cleanup([kid], me="api"), [kid])
        self.assertIn(board, self.h.closed)
        self.assertIn(agent_pane, self.h.closed)

    def test_the_closed_board_is_forgotten(self):
        """A remembered pane is what makes `_open_board` a no-op, so a stale one would
        mean a restored agent never gets a board again."""
        kid, _board, _pane = self._finished_kid()
        self.b.cleanup([kid], me="api")
        self.assertIsNone(self._board_pane(kid))

    def test_a_board_already_gone_is_tolerated(self):
        """Closed by hand, crashed, or never opened — all ordinary, none an error."""
        kid, board, _pane = self._finished_kid()
        self.h.panes.discard(board)                         # the human closed it
        real = self.h.close_pane
        def gone(pane):
            if pane == board:
                raise HerdrError("pane_not_found", f"no pane {pane}")
            real(pane)
        self.h.close_pane = gone
        self.assertEqual(self.b.cleanup([kid], me="api"), [kid])
        self.assertIsNone(self._board_pane(kid))

    def test_a_board_pane_an_agent_now_holds_is_not_closed(self):
        """A board pane id is recycled like any other, and herdr is machine-global — so
        the id we wrote down can be a stranger's agent pane by the time we close. A board
        carries no terminal id, so the rule is `_close_target`'s no-identity one: an empty
        pane may be closed, an occupied one may not. The record still goes, or the next
        `_open_board` under this name would believe a stranger's pane is our board."""
        kid, board, _pane = self._finished_kid()
        self.h.live["stranger"] = Agent(name="stranger", pane_id=board,
                                        terminal_id="term-theirs", state="working")
        self.assertEqual(self.b.cleanup([kid], me="api"), [kid])
        self.assertNotIn(board, self.h.closed)
        self.assertIsNone(self._board_pane(kid))

    def test_a_pane_that_would_not_close_keeps_its_board(self):
        """The agent is still in that pane, so the board beside it is still its view."""
        kid, board, _pane = self._finished_kid()
        def refuse(pane):
            raise HerdrError("close_failed", "no")
        self.h.close_pane = refuse
        self.assertEqual(self.b.cleanup([kid], me="api"), [])
        self.assertEqual(self._board_pane(kid), board)

    def _board_close_fails(self, board, exc):
        """Let every pane close except the board's, which fails with `exc`."""
        real = self.h.close_pane
        def sometimes(pane):
            if pane == board:
                raise exc
            real(pane)
        self.h.close_pane = sometimes
        return real

    def test_a_board_close_that_proves_nothing_is_retried_not_forgotten(self):
        """The stray-pane leak. A close that failed for a reason saying nothing about
        whether the pane is still ours used to drop the meta row anyway — and that row is
        the only thing pointing at the pane, so the pane was orphaned for good. Keep it,
        and let a later sweep close it."""
        kid, board, _pane = self._finished_kid()
        real = self._board_close_fails(board, HerdrError("close_failed", "herdr said no"))
        self.assertEqual(self.b.cleanup([kid], me="api"), [kid])
        self.assertEqual(self._board_pane(kid), board)      # still pointed at
        self.h.close_pane = real                            # herdr comes back
        self.b.cleanup(me="api")                            # a bare sweep is enough
        self.assertIn(board, self.h.closed)
        self.assertIsNone(self._board_pane(kid))

    def test_the_deferred_agent_row_is_not_held_open_on_its_dead_pane(self):
        """The retry must not ride on the agent's `pane_id`. Holding the row open would
        leave it pointing at a pane this sweep already closed — and herdr hands a freed
        pane id straight back out. The stranger who inherits it reads as a recycled-id
        mismatch, which refuses the row BEFORE the board is ever reached, forever, with
        `--force` the only way out: worse than the leak this fixes. So the row ends
        `done` with no pane, and the board is retried from the already-closed branch."""
        kid, board, agent_pane = self._finished_kid()
        real = self._board_close_fails(board, HerdrError("close_failed", "herdr said no"))
        self.assertEqual(self.b.cleanup([kid], me="api"), [kid])
        row = store.get_agent(self.db, kid)
        self.assertIsNone(row["pane_id"])                   # nothing left to recycle
        self.assertEqual(self._board_pane(kid), board)      # but the board is remembered
        # herdr forgets the agent and hands its pane id to somebody else, as it does.
        del self.h.live[kid]
        self.h.live["stranger"] = Agent(name="stranger", pane_id=agent_pane,
                                        terminal_id="term-theirs", state="working")
        self.h.close_pane = real
        # The broker caches one `agent list` per PROCESS, and in production the next
        # sweep is a new `sb`. One Broker across two sweeps is not, so without this the
        # stranger is invisible to sweep 2 and the recycle this test is named for never
        # happens — the test would pass against the wedge it exists to catch.
        self.b._forget_agent_caches()
        self.b.cleanup(me="api")
        self.assertIn(board, self.h.closed)                 # converged, not wedged
        self.assertIsNone(self._board_pane(kid))
        self.assertEqual(self.h.closed.count(agent_pane), 1)  # never the stranger's

    def test_a_herdr_that_cannot_be_asked_defers_the_board(self):
        """`_close_target`'s no-answer refusal is not a refusal about this pane at all —
        herdr was unreachable. Reading it as "not ours" is how the record got dropped."""
        kid, board, _pane = self._finished_kid()
        self.b._alive_cache, self.b._alive_unknown = None, False
        def down():
            raise HerdrError("herdr_down", "no herdr")
        self.h.list_agents = down
        self.assertFalse(self.b._close_board(kid))          # deferred, not settled
        self.assertEqual(self._board_pane(kid), board)
        self.assertNotIn(board, self.h.closed)

    def test_force_drops_a_board_it_could_not_close(self):
        """`--force` is the escape hatch for things that cannot be closed, so a board
        that defers must not wedge it: the row goes and the agent ends `done` anyway."""
        kid, board, _pane = self._finished_kid()
        self._board_close_fails(board, HerdrError("close_failed", "herdr said no"))
        self.assertEqual(self.b.cleanup([kid], me="api", force=True), [kid])
        self.assertIsNone(self._board_pane(kid))
        self.assertIsNone(store.get_agent(self.db, kid)["pane_id"])

class WorktreeIsAFactTest(Fixture, unittest.TestCase):
    """"Does this agent have a worktree?" is read from the store, never from the name.

    The `workspace` column says a branch for a worktree space and an agent-ish label for a
    bare one, and nothing distinguishes the two. `branch` does: NULL means bare. The fork
    rule asks `Broker.has_worktree`, and the landmine below is what the conflation cost —
    looking up a bare space's herdr id used to fork it a git branch and a checkout.
    """

    def test_a_workspace_lead_records_the_branch_it_works_on(self):
        r = self._open("api")
        self.assertEqual(r["branch"], "api")
        self.assertTrue(self.b.has_worktree("api"))
        self.assertEqual(self.b.worktree_branch("api"), "api")

    def test_the_top_level_orchestrators_space_is_bare(self):
        """`sb start` lays a workspace over the main checkout and never forks. The row has
        to say so, or its children inherit a checkout that is the human's."""
        b = Broker(self.db, self.h, repo=self._git_repo())
        name = b.start()
        self.assertIsNone(store.get_agent(self.db, name)["branch"])
        self.assertFalse(b.has_worktree(name))

    def test_a_bare_space_is_not_mistaken_for_a_named_checkout(self):
        """The recorded cwd of a bare space is the main checkout — real, and not this
        workspace's. Reading it as one is what made a label look like a worktree."""
        store.create_agent(self.db, name="root", role="lead", workspace="scratch",
                           cwd=str(self.repo))
        self.assertIsNone(self.b._recorded_path("scratch"))

    # -- the landmine ----------------------------------------------------

    def test_looking_up_a_bare_spaces_id_creates_no_branch_and_no_worktree(self):
        """`_workspace_id` fell through to `_attach_workspace`, whose create step runs
        `worktree create --branch <name>`. Merely resolving an id therefore forked a git
        branch and a checkout for a space that never had one."""
        store.create_agent(self.db, name="root", role="lead", workspace="scratch",
                           cwd=str(self.repo))
        self.assertEqual(self.b._workspace_id("scratch"), "")
        self.assertEqual(self.h.calls, [])                   # herdr was not even asked
        self.assertEqual(self.h.checkouts, {})

    def test_a_childs_placement_never_forks_its_parents_bare_space(self):
        """End to end, through the path that actually reached it: the last-resort tab
        placement for a child whose parent's workspace id we never recorded."""
        import os
        from unittest import mock
        store.create_agent(self.db, name="root", role="lead", workspace="scratch",
                           cwd=str(self.repo), pane_id="w1:p1", is_top=True)
        with mock.patch.dict(os.environ, {}, clear=True):
            kid = self.b.delegate("t", topic="t", role="worker", me="root")
        # The child forks — its parent is a top — but it forks its OWN name. What must
        # never happen is a checkout appearing under the parent's bare label.
        self.assertEqual(self.h.calls_of("create_worktree"), [kid])
        self.assertEqual(store.get_agent(self.db, kid)["workspace"], kid)

    def test_an_unknown_name_is_looked_up_never_created(self):
        """No row at all is not permission to fork one. The open is tried — a herdr
        restart loses workspaces our store never knew — and failing it is harmless."""
        self.assertEqual(self.b._workspace_id("mystery"), "")
        self.assertEqual(self.h.calls_of("create_worktree"), [])
        self.assertEqual(self.h.checkouts, {})

    def test_a_bare_space_never_shadows_a_worktree_of_the_same_name(self):
        """Two spaces may share a name — that is what the split is for. A branch belongs
        to the workspace it was recorded in, and is not inherited by name."""
        self._open("api", me=self._root("other-top"))        # worktree space 'api'
        store.create_agent(self.db, name="root", role="lead", workspace="api",
                           cwd=str(self.repo), is_top=True)  # a bare row, same name
        self.assertIsNone(store.get_agent(self.db, "root")["branch"])
        kid = self.b.delegate("t", topic="t", role="worker", me="root")
        # Its parent is a top, so it forks — and what it must not do is pick up the 'api'
        # worktree that merely shares its parent's label.
        self.assertNotEqual(store.get_agent(self.db, kid)["branch"], "api")
        self.assertEqual(store.get_agent(self.db, kid)["branch"], kid)

    def test_a_fork_still_creates_the_worktree_it_is_asked_for(self):
        """The lookup stopped creating; the path that means "make me one" must not."""
        self._open("api")
        self.assertEqual(self.h.calls_of("create_worktree"), ["api"])


class ForkRuleTest(Fixture, unittest.TestCase):
    """The fork rule: you get a space and worktree of your own when a TOP spawned you.

    Anyone else's spawn inherits the caller's space and shares it as a tab, and so does its
    whole subtree. Role-agnostic — there is no read-only exception, because "it will only
    read" is a claim about the future and the one bare space in the model is the human's
    own checkout.

    It used to key on the caller having no worktree, which coincides with top-ness for the
    agents that happen to exist and is not the same fact — `WorktreeIsNotTopnessTest`
    below is the case where they come apart.
    """

    def _bare_root(self, name: str = "root") -> str:
        """A top orchestrator's space: a herdr workspace over the main checkout, no branch
        of its own, STAMPED. What `sb start` produces."""
        store.create_agent(self.db, name=name, role="lead", workspace="scratch",
                           cwd=str(self.repo), pane_id="w1:p1", is_top=True)
        return name

    def test_a_child_of_a_top_is_forked_its_own_worktree(self):
        kid = self.b.delegate("t", topic="t", role="worker", me=self._bare_root())
        row = store.get_agent(self.db, kid)
        self.assertEqual(row["branch"], kid)                 # the branch IS the name
        self.assertEqual(row["workspace"], kid)
        self.assertEqual(self.h.calls_of("create_worktree"), [kid])
        self.assertNotEqual(row["cwd"], str(self.repo))      # not the human's checkout
        self.assertTrue(self.b.has_worktree(kid))

    def test_a_grandchild_inherits_its_parents_worktree_rather_than_forking(self):
        kid = self.b.delegate("t", topic="t", role="lead", me=self._bare_root())
        grandkid = self.b.delegate("t", topic="t", role="worker", me=kid)
        rows = [store.get_agent(self.db, n) for n in (kid, grandkid)]
        self.assertEqual(rows[1]["branch"], rows[0]["branch"])
        self.assertEqual(rows[1]["workspace"], rows[0]["workspace"])
        self.assertEqual(rows[1]["cwd"], rows[0]["cwd"])
        self.assertEqual(self.h.calls_of("create_worktree"), [kid])   # exactly one fork

    def test_the_human_has_no_worktree_to_lend_so_their_child_forks(self):
        kid = self.b.delegate("t", topic="t", role="worker", me=HUMAN)
        self.assertEqual(store.get_agent(self.db, kid)["branch"], kid)

    def test_the_question_is_asked_of_the_store_not_of_the_name(self):
        """A top's bare space whose label happens to name a real branch must still fork.
        The name cannot answer this — only the stamp can."""
        r = self._open("api", me=self._root("other-top"))    # a real worktree named 'api'
        store.create_agent(self.db, name="root", role="lead", workspace="api",
                           cwd=str(self.repo), pane_id="w1:p1",   # a BARE space, same name
                           is_top=True)
        kid = self.b.delegate("t", topic="t", role="worker", me="root")
        self.assertEqual(store.get_agent(self.db, kid)["branch"], kid)
        self.assertNotEqual(store.get_agent(self.db, kid)["cwd"], r["path"])

    def test_a_caller_that_names_the_workspace_is_not_overridden(self):
        """`sb start` and a workspace lead both place a child explicitly. A fork on top of
        that would ignore the instruction."""
        r = self._open("api", me=self._root("other-top"))
        kid = self.b.delegate("t", topic="t", role="worker", me=self._bare_root(),
                              workspace="api", branch="api", cwd=r["path"])
        self.assertEqual(store.get_agent(self.db, kid)["workspace"], "api")
        self.assertEqual(self.h.calls_of("create_worktree"), ["api"])

    def test_the_child_takes_the_forked_workspaces_root_pane(self):
        """A fresh workspace already has an idle shell; a tab on top of it is a pane
        nobody ever closes."""
        kid = self.b.delegate("t", topic="t", role="worker", me=self._bare_root())
        self.assertEqual(self.h.tabs, [])
        self.assertEqual(store.get_agent(self.db, kid)["pane_id"],
                         self.h.checkouts[store.get_agent(self.db, kid)["cwd"]]["root_pane"])

    # -- the collision refusal -------------------------------------------

    def test_a_branch_that_already_exists_refuses_the_fork(self):
        """Never silently reused: that branch is somebody else's work, with somebody
        else's commits on it."""
        import subprocess
        main = self._git_repo()
        subprocess.run(["git", "branch", "spike"], cwd=main, capture_output=True)
        b = Broker(self.db, self.h, repo=main)
        store.create_agent(self.db, name="root", role="lead", cwd=str(main),
                           is_top=True)
        with self.assertRaises(ValueError) as cm:
            b.delegate("t", role="worker", name="spike", me="root")
        self.assertIn("spike", str(cm.exception))
        self.assertIn("already exists", str(cm.exception))

    def test_the_refusal_names_both_ways_forward(self):
        import subprocess
        main = self._git_repo()
        subprocess.run(["git", "branch", "spike"], cwd=main, capture_output=True)
        b = Broker(self.db, self.h, repo=main)
        store.create_agent(self.db, name="root", role="lead", cwd=str(main),
                           is_top=True)
        with self.assertRaises(ValueError) as cm:
            b.delegate("t", role="worker", name="spike", me="root")
        self.assertIn("--name", str(cm.exception))           # spawn under another name
        self.assertIn("--workspace spike", str(cm.exception))   # or join what is there

    def test_a_refused_fork_spawns_nothing_and_holds_no_name(self):
        """Refused BEFORE anything is claimed, so the name is free for the retry the
        message asks for."""
        import subprocess
        main = self._git_repo()
        subprocess.run(["git", "branch", "spike"], cwd=main, capture_output=True)
        b = Broker(self.db, self.h, repo=main)
        store.create_agent(self.db, name="root", role="lead", cwd=str(main),
                           is_top=True)
        with self.assertRaises(ValueError):
            b.delegate("t", role="worker", name="spike", me="root")
        self.assertIsNone(store.get_agent(self.db, "spike"))
        self.assertEqual(self.h.started, [])
        self.assertEqual(self.h.checkouts, {})

    def test_the_branch_the_agent_is_named_after_is_the_one_checked_for(self):
        """An unrelated branch is not a collision — only this agent's own name is."""
        import subprocess
        main = self._git_repo()
        subprocess.run(["git", "branch", "somebody-else"], cwd=main, capture_output=True)
        b = Broker(self.db, self.h, repo=main)
        store.create_agent(self.db, name="root", role="lead", cwd=str(main),
                           is_top=True)
        kid = b.delegate("t", role="worker", name="spike", me="root")
        self.assertEqual(store.get_agent(self.db, kid)["branch"], "spike")

    def test_an_inheriting_child_is_never_refused_over_a_branch(self):
        """The refusal belongs to forking. A child that inherits its parent's worktree
        touches no branch, so a branch of its name is none of its business."""
        import subprocess
        main = self._git_repo()
        subprocess.run(["git", "branch", "spike"], cwd=main, capture_output=True)
        b = Broker(self.db, self.h, repo=main)
        r = self._open("api", b=b)
        kid = b.delegate("t", role="worker", name="spike", me="api")
        self.assertEqual(store.get_agent(self.db, kid)["cwd"], r["path"])


class ForkBaseTest(Fixture, unittest.TestCase):
    """Where a fork starts from: `origin/main`, fetched on the spot.

    A local `main` is however stale the last pull left it, so the base is the
    remote-tracking ref and it is refreshed at the moment of the fork. None of that may
    cost a spawn: a laptop with no network still forks, just from what it already has.
    """

    def setUp(self):
        super().setUp()
        self.bases: list[str] = []
        real = self.h.create_worktree
        def recording(branch, *, base="main", **kw):         # noqa: E306
            self.bases.append(base)
            return real(branch, base=base, **kw)
        self.h.create_worktree = recording

    @staticmethod
    def _git(where: Path, *args: str):
        import subprocess
        return subprocess.run(["git", *args], cwd=where, capture_output=True, text=True)

    def _repo_with_origin(self) -> Path:
        """A main checkout with a real remote — a bare repo next door, so a fetch is a
        real fetch with no network in it."""
        main = self._git_repo()
        origin = self.repo / "origin.git"
        self._git(self.repo, "init", "-q", "--bare", "-b", "main", str(origin))
        self._git(main, "remote", "add", "origin", str(origin))
        self._git(main, "push", "-q", "origin", "main")
        return main

    def _tracking(self, main: Path) -> bool:
        return self._git(main, "rev-parse", "--verify", "--quiet",
                         "refs/remotes/origin/main").returncode == 0

    def test_the_base_is_fetched_on_the_spot_and_forked_from(self):
        main = self._repo_with_origin()
        self._git(main, "update-ref", "-d", "refs/remotes/origin/main")   # never fetched
        self.assertFalse(self._tracking(main))
        self._open("api", b=Broker(self.db, self.h, repo=main))
        self.assertTrue(self._tracking(main), "the fork fetched the base first")
        self.assertEqual(self.bases, ["origin/main"])
        self.assertEqual(self._fork_event()["base"], "origin/main")
        self.assertIsNone(self._fork_event()["base_fallback"])

    def test_a_failed_fetch_falls_back_to_the_local_copy_and_carries_on(self):
        """No network is not a reason to lose a spawn — it is a reason to fork from the
        `origin/main` we already have."""
        main = self._repo_with_origin()
        self._git(main, "remote", "set-url", "origin", str(self.repo / "gone.git"))
        r = self._open("api", b=Broker(self.db, self.h, repo=main))
        self.assertEqual(self.bases, ["origin/main"])        # the local copy of it
        self.assertEqual(self._fork_event()["base_fallback"], "fetch_failed")
        self.assertTrue(r["path"])                           # and the workspace exists
        self.assertIn("api", self.h.live)

    def test_no_remote_at_all_falls_back_to_the_local_base(self):
        """A repo with one `main` and no remote: forking from it is not a degradation,
        it is the only meaningful answer — so nothing is logged as a failure."""
        main = self._git_repo()                              # no origin
        self._open("api", b=Broker(self.db, self.h, repo=main))
        self.assertEqual(self.bases, ["main"])
        self.assertEqual(self._fork_event()["base_fallback"], "no_remote")
        self.assertNotIn("fetch_failed",
                         [e["kind"] for e in store.recent_events(self.db)])

    def test_a_fork_from_delegate_fetches_too(self):
        """The path that matters: the fork rule's own create, under its own name."""
        main = self._repo_with_origin()
        self._git(main, "update-ref", "-d", "refs/remotes/origin/main")
        b = Broker(self.db, self.h, repo=main)
        store.create_agent(self.db, name="root", role="lead", cwd=str(main),
                           pane_id="w1:p1", is_top=True)
        b.delegate("t", topic="t", role="worker", me="root")
        self.assertEqual(self.bases, ["origin/main"])
        self.assertTrue(self._tracking(main))

    def test_joining_an_existing_workspace_fetches_nothing(self):
        """Nothing is being forked, so there is no base to be stale."""
        main = self._repo_with_origin()
        b = Broker(self.db, self.h, repo=main)
        self._open("api", b=b)
        b.join_workspace("api")                              # somebody else joins it
        self.assertEqual(len(self.bases), 1)


class JoinWorkspaceTest(Fixture, unittest.TestCase):
    """`sb delegate --workspace <name>` — join a workspace somebody already opened.

    The other half of the fork rule: a spawn either forks its own worktree or joins one by
    name, and a joined workspace is shared — same branch, same checkout, same herdr
    workspace, however many agents are in it. The one thing it must never do is create,
    because `--workspace` is what you type when a fork was refused.
    """

    def _join(self, name: str, *, me: str = "root") -> str:
        return self.b.delegate("t", topic="t", role="worker", me=me,
                               **self.b.join_workspace(name))

    def setUp(self):
        super().setUp()
        store.create_agent(self.db, name="root", role="lead", workspace="scratch",
                           cwd=str(self.repo), pane_id="w1:p1", is_top=True)

    def test_a_child_joins_the_named_workspace_instead_of_its_parents(self):
        r = self._open("api", me=self._root("other-top"))
        row = store.get_agent(self.db, self._join("api"))
        self.assertEqual(row["workspace"], "api")
        self.assertEqual(row["branch"], "api")
        self.assertEqual(row["cwd"], r["path"])
        self.assertEqual(row["workspace_id"], r["workspace_id"])

    def test_joining_disturbs_no_lead(self):
        """Joining is not opening: the workspace's lead is left exactly as it was."""
        self._open("api", me=self._root("other-top"))
        started = len(self.h.started)
        self._join("api")
        self.assertEqual(len(self.h.started), started + 1)
        self.assertEqual(store.get_agent(self.db, "api")["state"], "working")

    # -- what it refuses -------------------------------------------------

    def test_a_workspace_nobody_opened_is_refused_never_forked(self):
        with self.assertRaises(ValueError) as e:
            self.b.join_workspace("nope")
        self.assertIn("never forks", str(e.exception))
        self.assertEqual(self.h.calls_of("create_worktree"), [])
        self.assertEqual(self.h.checkouts, {})

    def test_a_bare_space_is_refused_and_forks_nothing(self):
        """A top-level orchestrator's space has no checkout of its own to share, and
        asking herdr for one by that name is how a label used to become a branch."""
        with self.assertRaises(ValueError) as e:
            self.b.join_workspace("scratch")
        self.assertIn("bare space", str(e.exception))
        self.assertEqual(self.h.calls, [])
        self.assertEqual(self.h.checkouts, {})

    # -- the flag --------------------------------------------------------

class RetiringMarkExcludesTest(Fixture, unittest.TestCase):
    """The retiring mark keeps people OUT — which is the whole reason it is written first.

    `sb workspace close` commits the mark before it starts destroying, and its concurrency
    argument rests on nobody being able to walk into the workspace while it is being taken
    apart. Written and read only by the command that wrote it, the mark excludes nobody, so
    there is a test per door into a workspace: forking one, joining one, starting a
    top-level orchestrator in a bare one, and restoring an agent back into one. Forking is
    the door `sb workspace new` used to be: with the verb deleted, `_fork_for` is what has
    to read the mark, and a branch check is not a substitute — it refuses on a different
    fact and says nothing about a checkout being removed.

    It refuses either way, alive owner or dead one — a teardown that died partway through
    leaves a half-taken-apart checkout, and the way back is `--resume` on the command that
    set the mark, not a second verb that clears it by joining the name.
    """

    def marked(self, name: str = "api", owner: str = "tidy-up", *,
               state: str = "working", bare: bool = False) -> None:
        """A workspace some other agent is mid-teardown of."""
        store.record_workspace(self.db, name, None if bare else f"/wt/{name}")
        store.create_agent(self.db, name=owner, role="worker", cwd=str(self.repo))
        store.set_state(self.db, owner, state)
        if state in ("working", "blocked"):
            self.h.live[owner] = Agent(name=owner, pane_id="w9:p1", state="working")
        self.assertTrue(store.claim_retiring(self.db, name, owner))

    def test_forking_into_a_workspace_being_taken_apart_is_refused(self):
        self.marked()
        with self.assertRaises(ValueError) as e:
            self._open("api")
        self.assertIn("tidy-up", str(e.exception))
        self.assertEqual(self.h.calls_of("create_worktree"), [])
        self.assertNotIn("api", self.h.live)

    def test_joining_a_workspace_being_taken_apart_is_refused(self):
        self.marked()
        with self.assertRaises(ValueError) as e:
            self.b.join_workspace("api")
        self.assertIn("tidy-up", str(e.exception))

    def test_it_still_refuses_when_the_mark_owner_is_confirmed_gone(self):
        """Deliberate. `--resume` belongs to `sb workspace close`, which discloses the dead
        owner and re-runs the teardown; it is not an invitation to walk into a
        half-destroyed checkout."""
        self.marked(state="failed")
        for verb in (lambda: self._open("api"),
                     lambda: self.b.join_workspace("api")):
            with self.assertRaises(ValueError) as e:
                verb()
            self.assertIn("tidy-up", str(e.exception))

    def test_starting_an_orchestrator_in_a_bare_workspace_being_closed_is_refused(self):
        """Bare workspaces are closeable too, and `sb start --name` is the other door in."""
        self.marked("main-2", bare=True)
        with self.assertRaises(ValueError) as e:
            self.b.start(name="main-2")
        self.assertIn("tidy-up", str(e.exception))
        self.assertIsNone(store.get_agent(self.db, "main-2"))

    def test_restore_will_not_bring_an_agent_back_into_one(self):
        """A restored agent comes back into the checkout it was recorded in — which here is
        the directory the teardown is about to remove."""
        self.marked()
        store.create_agent(self.db, name="api-lead", role="workspace", workspace="api",
                           session_id="sess", cwd="/wt/api")
        with self.assertRaises(ValueError) as e:
            self.b.restore("api-lead")
        self.assertIn("tidy-up", str(e.exception))
        self.assertEqual(self.h.tabs, [])

    # -- and nothing else changed ----------------------------------------

    def test_an_unmarked_workspace_is_opened_and_joined_exactly_as_before(self):
        """The regression that matters most: ordinary workspace creation is untouched."""
        r = self._open("api")
        self.assertEqual(self._branches(), ["api"])
        self.assertEqual(self.b.join_workspace("api")["workspace_id"], r["workspace_id"])

    def test_releasing_the_mark_makes_the_name_usable_again(self):
        """A teardown that refuses clears its own mark, and the workspace it declined to
        destroy is an ordinary one again."""
        self.marked()
        store.release_retiring(self.db, "api", "tidy-up")
        self.assertEqual(self._open("api")["workspace"], "api")


class PluginsOnEverySpawnPathTest(unittest.TestCase):
    """A repo's plugin bindings reach EVERY spawn, not just `sb delegate`'s.

    While resolution lived in the CLI's `delegate` branch, the other spawn verbs called
    `Broker.delegate` straight past it, so a workspace lead and the top-level orchestrator
    silently missed the repo's every-agent bindings — a lead never received `own-files`.
    One resolution point in `Broker.delegate` is the fix.

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
        kid = self.b.delegate("t", topic="t", role="worker", me=HUMAN)
        self.assertIn("keep it short", " ".join(self._prompts_for(kid)))

    def test_every_spawn_path_resolves_the_same_bindings(self):
        """The property the fix is really about: one resolution point, not three."""
        kid = self.b.delegate("t", topic="t", role="lead", me=HUMAN)
        store.create_agent(self.db, name="root", role="lead", workspace="scratch",
                           cwd=str(self.repo), pane_id="w1:p1", is_top=True)
        lead = self.b.delegate("t", role="lead", name="api", me="root")
        top = self.b.start()
        plugins = [[p for p in self._prompts_for(n) if "keep it short" in p]
                   for n in (kid, lead, top)]
        self.assertEqual(plugins[0], plugins[1])
        self.assertEqual(plugins[1], plugins[2])
        self.assertEqual(len(plugins[0]), 1, "flattened to one line, and not duplicated")

    def test_a_per_role_binding_still_layers_on_top(self):
        """`all` then the role's own — the layering survives the move."""
        kid = self.b.delegate("t", topic="t", role="worker", me=HUMAN)
        text = " ".join(self._prompts_for(kid))
        self.assertIn("keep it short", text)
        self.assertIn("be exact", text)

    def test_a_callers_own_with_is_appended_last(self):
        kid = self.b.delegate("t", topic="t", role="worker", with_=["house-style", "and terse"],
                              me=HUMAN)
        prompts = self._prompts_for(kid)
        self.assertIn("and terse", prompts)
        self.assertEqual(len([p for p in prompts if "keep it short" in p]), 1,
                         "already bound for every agent; naming it again adds nothing")

    def test_a_plugin_that_cannot_flatten_names_the_plugin(self):
        """The CLI's error quality has to survive the move: this is what becomes an agent
        argument, so a plugin that flattens to something herdr rejects must say so."""
        over = config.setting("limits.prompt") + 1
        (self.repo / ".switchboard" / "plugins" / "house-style.md").write_text("x" * over)
        with self.assertRaises(ValueError) as cm:
            self.b.delegate("t", topic="t", role="worker", me=HUMAN)
        self.assertIn("preset text", str(cm.exception))


class RestoreOpensTheBoardTest(Fixture, unittest.TestCase):
    """A restored agent comes back into the same two panes a spawned one opens in.

    `delegate` is the one place every SPAWN passes through, and restore is not a spawn —
    it makes its own tab and starts its own agent — so it was the one door that opened a
    single full-width pane with no board beside it.
    """

    def _closed_kid(self) -> str:
        """A child that has been closed: row and session kept, panes gone."""
        self._open("api")
        kid = self.b.delegate("t", topic="t", role="worker", me="api")
        store.set_state(self.db, kid, "done")
        self.assertEqual(self.b.cleanup([kid], me="api"), [kid])
        # The fake keeps a closed agent in `live`; real herdr drops it with its pane,
        # and `restore` refuses an agent herdr still lists as running.
        self.h.live.pop(kid, None)
        self.h.splits.clear()
        self.h.split_cwds.clear()
        self.h.pane_prompts.clear()
        return kid

    def test_a_restored_agent_gets_a_board_beside_it(self):
        kid = self._closed_kid()
        self.b.restore(kid, me=HUMAN)
        pane = store.get_agent(self.db, kid)["pane_id"]
        self.assertEqual([(p, d) for p, d, _r in self.h.splits], [(pane, "right")])
        self.assertIn("switchboard.board", _board_line(self.h)[1])

    def test_the_restored_board_reads_the_agents_own_checkout(self):
        """A board pointed at the main checkout looks right and reports the wrong tree."""
        kid = self._closed_kid()
        self.b.restore(kid, me=HUMAN)
        where = store.get_agent(self.db, kid)["cwd"]
        self.assertEqual(self.h.split_cwds, [where])
        self.assertNotEqual(where, str(self.repo))

    def test_a_restore_still_succeeds_when_the_split_fails(self):
        """The board is a view; restore must not fail because one would not open."""
        kid = self._closed_kid()
        def boom(*a, **kw):
            raise HerdrError("split_failed", "no panes left")
        self.h.split_pane = boom
        self.b.restore(kid, me=HUMAN)
        self.assertIn(kid, self.h.live)
        self.assertTrue(any(e["kind"] == "board_open_failed"
                            for e in store.recent_events(self.db)))


if __name__ == "__main__":
    unittest.main()
