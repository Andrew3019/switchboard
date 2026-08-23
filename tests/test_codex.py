"""The codex provider seam — the per-agent home, the spawn, and reading a rollout back.

What a test can pin here is the SHAPE: that the home carries everything a codex spawn
needs, that a restore does not wipe the standing instructions, that the spawn passes
codex's flags and none of Claude Code's, and that a rollout record renders. What it
cannot pin is that codex honours any of it, so that half was proved live against
codex-cli 0.147.0 instead — the config keys parse under `--strict-config`, both hooks
fire with arguments, the auth symlink authenticates a real turn, and `AGENTS.md` from a
private `CODEX_HOME` is obeyed. The comments say which claim rests on which.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import codex, models, output, store  # noqa: E402
from switchboard.broker import HUMAN, Broker  # noqa: E402
from switchboard.herdr import Herdr  # noqa: E402
from tests.test_broker import FakeHerdrAPI  # noqa: E402
from tests.test_models import _StubBroker  # noqa: E402
from tests.test_herdr import AGENT_JSON, FakeHerdr, ok  # noqa: E402


def _git_repo(path: Path) -> Path:
    """A real repo, because `store.store_dir` asks git for the shared `.git` rather than
    looking for a directory of that name — a worktree's is a file."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, capture_output=True)
    return path


class HomeFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = _git_repo(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name="w1", **kw):
        kw.setdefault("prompts", ["you are w1", "call sb done"])
        kw.setdefault("worktree", str(self.repo))
        kw.setdefault("model", "gpt-5.5")
        kw.setdefault("effort", "medium")
        return codex.write_home(name, cwd=self.repo, **kw)

    def config(self, home: Path) -> dict:
        return tomllib.loads((home / "config.toml").read_text())


class CodexHomeTest(HomeFixture, unittest.TestCase):
    def test_the_home_carries_everything_a_spawn_needs(self):
        """One directory in place of five Claude Code flags. Every key here was verified
        to parse under `codex --strict-config` and to take effect, not merely be accepted:
        the model and effort showed up in the rollout log, the sandbox refused a write
        outside the workspace, and the trust entry stopped the TUI blocking on its prompt
        in a checkout that CODEX_HOME had never seen."""
        home = self.write()
        cfg = self.config(home)
        self.assertEqual(cfg["model"], "gpt-5.5")
        self.assertEqual(cfg["model_reasoning_effort"], "medium")
        self.assertEqual(cfg["sandbox_mode"], "workspace-write")
        self.assertEqual(cfg["approval_policy"], "never")
        # Trust is keyed by the RESOLVED absolute path — codex matches on the path it
        # computes for its own cwd, and a checkout reached through a symlinked /tmp is a
        # different string.
        self.assertIn(str(self.repo.resolve()), cfg["projects"])
        self.assertEqual(cfg["projects"][str(self.repo.resolve())]["trust_level"],
                         "trusted")
        # What `workspace-write` alone does not cover, both found by running a real agent:
        # the store is under the SHARED `.git`, which a worktree agent is not standing
        # anywhere near, and the herdr socket is under the human's config dir — without
        # them `sb done` cannot write and every herdr call fails PermissionDenied. Network
        # access is off by default in this mode, which is not what `--permission-mode auto`
        # means for a claude agent.
        roots = cfg["sandbox_workspace_write"]["writable_roots"]
        self.assertTrue(any(r.endswith("agentflow") for r in roots), roots)
        self.assertTrue(any("herdr" in r for r in roots), roots)
        self.assertTrue(cfg["sandbox_workspace_write"]["network_access"])
        # The prompt, unflattened. The single-line rule is herdr's, about ARGUMENTS, and
        # nothing on this path is one.
        text = (home / "AGENTS.md").read_text()
        self.assertIn("you are w1", text)
        self.assertIn("call sb done", text)
        self.assertIn("\n", text)

    def test_auth_is_a_symlink_to_the_one_credential(self):
        """Decided, not incidental (Andrew, 2026-08-22): a copy would be a second
        credential per agent, stale the moment the human re-logs in. A private CODEX_HOME
        with neither 401s on every request — verified live."""
        src = self.repo / "real-auth.json"
        src.write_text("{}")
        with mock.patch.object(codex, "AUTH_FILE", str(src)):
            home = self.write()
        link = home / "auth.json"
        self.assertTrue(link.is_symlink())
        self.assertEqual(Path.readlink(link), src)

    def test_the_hooks_block_wires_the_events_it_is_given(self):
        home = self.write(hooks={"Stop": "/bin/gate --db /x", "UserPromptSubmit": "/bin/a"})
        cfg = self.config(home)
        stop = cfg["hooks"]["Stop"][0]
        self.assertEqual(stop["matcher"], "*")
        self.assertEqual(stop["hooks"][0]["type"], "command")
        # Arguments survive the TOML quoting AND codex's own splitting — the second half
        # verified live: a hook command carrying `--db <path>` ran with that argv.
        self.assertEqual(stop["hooks"][0]["command"], "/bin/gate --db /x")
        self.assertEqual(cfg["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"],
                         "/bin/a")

    def test_a_restore_does_not_wipe_the_standing_instructions(self):
        """THE ONE THAT WOULD BITE SILENTLY. `restore` composes no prompts — Claude Code's
        `--resume` brings the system prompt back with the session — but codex re-reads
        `AGENTS.md` every turn, so writing an empty one here would restore an agent into
        its own context with no protocol at all."""
        home = self.write()
        before = (home / "AGENTS.md").read_text()
        self.write(prompts=[])
        self.assertEqual((home / "AGENTS.md").read_text(), before)
        # The rest of the home IS rewritten — a restore may be on a different tier.
        self.assertEqual(self.config(home)["model"], "gpt-5.5")

    def test_a_home_is_evidence_of_the_provider_and_goes_with_the_agent(self):
        """`is_codex_agent` asks the directory rather than re-resolving the row's tier: a
        tier is config that may since have been edited to mean something else, while the
        directory exists only because a codex spawn wrote it."""
        self.assertFalse(codex.is_codex_agent("w1", self.repo))
        self.write()
        self.assertTrue(codex.is_codex_agent("w1", self.repo))
        codex.forget_home("w1", self.repo)
        self.assertFalse(codex.is_codex_agent("w1", self.repo))

    def test_a_name_that_is_not_an_agent_name_is_refused(self):
        for bad in ("../escape", "", "a/b"):
            with self.subTest(name=bad), self.assertRaises(codex.CodexHomeError):
                codex.home_path(bad, self.repo)


class RolloutTest(HomeFixture, unittest.TestCase):
    SID = "01a02c19-22e8-7641-b219-cae9025f4f06"

    def rollout(self, name="w1", sid=None, day="2026/08/22") -> Path:
        sid = sid or self.SID
        d = codex.home_path(name, self.repo) / "sessions" / day
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"rollout-2026-08-22T17-50-40-{sid}.jsonl"
        p.write_text("")
        return p

    def test_a_session_id_is_found_by_filename_and_by_recency(self):
        """Both routes exist because the primary one is the hook payload and this is the
        fallback for a spawn whose hooks never fired — an untrusted codex hook is skipped
        silently, so that is a real case and not a hypothetical."""
        self.write()
        p = self.rollout()
        self.assertEqual(codex.newest_session_id("w1", self.repo), self.SID)
        self.assertEqual(codex.rollout_path("w1", self.SID, self.repo), p)
        self.assertIsNone(codex.rollout_path("w1", "no-such-id", self.repo))

    TUI_PROMPT = {"type": "event_msg",
                  "payload": {"type": "item_completed",
                              "item": {"type": "UserMessage",
                                       "content": [{"type": "text",
                                                    "text": "do the thing"}]}}}
    EXEC_PROMPT = {"type": "event_msg",
                   "payload": {"type": "user_message", "message": "do the thing"}}

    def test_a_delivered_task_is_confirmed_from_the_agent_s_own_rollout(self):
        """The spike found this the expensive way, twice. First there was no codex proof
        at all, so a task that landed on the first send was re-sent the full three times
        and done three times over — idempotent that time; a `git push` would not be. Then
        the proof read only the `exec`-mode record, which the TUI never writes, and the
        second spike did exactly the same thing again."""
        for shape in ("TUI_PROMPT", "EXEC_PROMPT"):
            with self.subTest(shape=shape):
                self.write()
                self.rollout().write_text(json.dumps(getattr(self, shape)) + "\n")
                self.assertTrue(
                    codex.task_arrived("w1", "do the thing", since=0, cwd=self.repo))
                self.assertFalse(
                    codex.task_arrived("w1", "some other task", since=0, cwd=self.repo))

    def test_only_a_submitted_message_counts_as_arrival(self):
        """The same text appears again in the assistant's reply and in any shell command
        that echoes it, and either would confirm a delivery that never happened."""
        self.write()
        self.rollout().write_text(json.dumps(
            {"type": "event_msg",
             "payload": {"type": "item_completed",
                         "item": {"type": "AgentMessage",
                                  "content": [{"type": "Text",
                                               "text": "do the thing"}]}}}) + "\n")
        self.assertFalse(codex.task_arrived("w1", "do the thing", since=0, cwd=self.repo))

    def test_a_claude_agent_has_no_rollouts_to_find(self):
        self.assertIsNone(codex.newest_session_id("w1", self.repo))
        self.assertIsNone(codex.sessions_dir("w1", self.repo))


class RolloutRenderTest(unittest.TestCase):
    """`sb inspect`'s transcript view, on the other format.

    Codex writes an outer `{timestamp, type, payload}` envelope around `event_msg` and
    `response_item` records, which the Claude renderer drops on the floor — every record
    in a real rollout rendered to nothing before this. Every record below is copied from
    a real rollout produced by a live `codex exec` run.
    """

    def render(self, *records) -> str:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "rollout.jsonl"
            p.write_text("\n".join(json.dumps(r) for r in records))
            return output.read_transcript(p, lines=50)

    def test_the_two_sides_of_a_turn_render(self):
        text = self.render(
            {"type": "session_meta", "payload": {"session_id": "x"}},
            {"type": "event_msg",
             "payload": {"type": "user_message", "message": "Say the single word PONG"}},
            {"type": "event_msg",
             "payload": {"type": "agent_message", "message": "PONG"}},
        )
        self.assertIn("user: Say the single word PONG", text)
        self.assertIn("assistant: PONG", text)
        # The meta record is noise for this purpose, exactly as Claude's summaries are.
        self.assertNotIn("session_meta", text)

    def test_the_tui_s_own_item_stream_is_what_is_read(self):
        """Records copied from a real spawn. The TUI writes `item_completed` and no
        `user_message`/`agent_message` event at all — reading only the `exec`-mode shapes
        is a viewer that shows an empty transcript for every agent switchboard spawns."""
        text = self.render(
            {"type": "event_msg",
             "payload": {"type": "item_completed",
                         "item": {"type": "UserMessage",
                                  "content": [{"type": "text", "text": "do the thing"}]}}},
            {"type": "event_msg",
             "payload": {"type": "item_completed",
                         "item": {"type": "AgentMessage",
                                  "content": [{"type": "Text", "text": "done it"}]}}},
        )
        self.assertIn("user: do the thing", text)
        self.assertIn("assistant: done it", text)

    def test_commands_and_edits_are_kept_and_reasoning_is_not(self):
        """Kept for the Claude renderer's reason: this is read when something has already
        gone wrong, and that is usually where the cause is. Reasoning is dropped for its
        other reason — it never reached the terminal either."""
        text = self.render(
            {"type": "event_msg",
             "payload": {"type": "item_completed",
                         "item": {"type": "CommandExecution",
                                  "command": ["/bin/zsh", "-lc", "ls"],
                                  "stdout": "a.txt", "exit_code": 0}}},
            {"type": "event_msg",
             "payload": {"type": "item_completed",
                         "item": {"type": "FileChange",
                                  "changes": {"/w/SPIKE.txt": {"type": "add"}}}}},
            {"type": "event_msg",
             "payload": {"type": "item_completed",
                         "item": {"type": "Reasoning", "summary_text": ["thinking"]}}},
        )
        self.assertIn("[exec]", text)
        self.assertIn("ls", text)
        self.assertIn("[result] a.txt", text)
        self.assertIn("[edit] /w/SPIKE.txt", text)
        self.assertNotIn("thinking", text)

    def test_a_claude_transcript_still_renders_the_claude_way(self):
        """The dispatch is per RECORD, and the two vocabularies share no `type` value —
        so nothing that worked before this can fall into the codex branch."""
        text = self.render(
            {"type": "user", "message": {"role": "user", "content": "hello"}},
            {"type": "assistant",
             "message": {"role": "assistant",
                         "content": [{"type": "text", "text": "hi"}]}},
        )
        self.assertIn("user: hello", text)
        self.assertIn("assistant: hi", text)


class CodexSpawnTest(unittest.TestCase):
    """What `agent start` is actually handed for a codex tier."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = _git_repo(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, spec, **kw) -> str:
        fake = FakeHerdr(ok({"agent": AGENT_JSON}))
        Herdr("herdr", runner=fake).start_agent(
            "w1", "w1:p9", prompts=["you are w1"], spec=spec, cwd=self.repo, **kw)
        return fake.argv()

    def spec(self, provider="codex"):
        return models.ModelSpec(tier="gpt-5.5", provider=provider,
                                model="gpt-5.5", effort="medium")

    def test_a_codex_spawn_passes_codex_flags_and_none_of_claude_s(self):
        """The seam, from the outside. Claude Code's five per-agent flags do not exist on
        `codex`, and passing one is a spawn that dies on an unknown argument."""
        argv = self.start(self.spec())
        self.assertIn("--kind codex", argv)
        self.assertIn("--dangerously-bypass-hook-trust", argv)
        # Loud rather than fail-open: an unrecognised key in a file WE wrote means codex
        # has moved on, and a silently ignored `hooks` block is a `sb done` gate that is
        # not there.
        self.assertIn("--strict-config", argv)
        for flag in ("--append-system-prompt-file", "--permission-mode", "--settings",
                     "--model", "--effort"):
            self.assertNotIn(flag, argv)

    def test_a_restore_becomes_the_resume_subcommand(self):
        """Codex has no `--resume` flag at all; `codex resume <SESSION_ID>` is a
        subcommand, and global options come before it per its own usage line."""
        argv = self.start(self.spec(), resume="01a0-thread-id")
        self.assertIn("resume 01a0-thread-id", argv)
        self.assertNotIn("--resume", argv)

    def test_a_claude_spawn_is_untouched_by_any_of_it(self):
        """The other half of a seam is that the existing side does not move."""
        argv = self.start(models.ModelSpec(tier="strong", provider="claude",
                                           model="opus", effort="high"),
                          model_args=["--model", "opus", "--effort", "high"])
        self.assertIn("--kind claude", argv)
        self.assertIn("--append-system-prompt-file", argv)
        self.assertIn("--permission-mode", argv)
        self.assertIn("--model opus", argv)
        self.assertNotIn("--dangerously-bypass-hook-trust", argv)


class PaneEnvTest(unittest.TestCase):
    """`--env` on the three calls that CREATE a pane, and only those three.

    herdr fixes a pane's environment when its shell is launched and `agent start` has no
    `--env` at all, so anything the agent's process must see has to be decided before the
    pane exists. Verified live that a variable set this way survives into the subprocesses
    codex's own shell tool runs, which is where every `sb` verb an agent types runs.
    """

    def call(self, method, *args, **kw):
        fake = FakeHerdr(ok({"root_pane": {"pane_id": "w1:p2"},
                             "pane": {"pane_id": "w1:p2"},
                             "workspace": {"workspace_id": "w1"}}))
        getattr(Herdr("herdr", runner=fake), method)(*args, **kw)
        return fake.argv()

    def test_every_pane_creating_call_takes_env(self):
        env = {"SB_AGENT": "w1", "CODEX_HOME": "/store/codex-homes/w1"}
        for method, args in (("create_tab", ()),
                             ("create_workspace", ("w1",)),
                             ("split_pane", ("w1:p1",))):
            with self.subTest(method=method):
                argv = self.call(method, *args, env=env)
                self.assertIn("--env SB_AGENT=w1", argv)
                self.assertIn("--env CODEX_HOME=/store/codex-homes/w1", argv)

    def test_no_env_means_no_flags(self):
        self.assertNotIn("--env", self.call("create_tab"))

    def test_a_key_that_would_become_a_different_variable_is_refused(self):
        """A `=` in the VALUE is fine — herdr's own split is unambiguous — and a `=` in
        the key would silently set something else."""
        with self.assertRaises(ValueError):
            self.call("create_tab", env={"A=B": "c"})


class DelegateOntoCodexTest(unittest.TestCase):
    """The end a person actually types: `sb delegate --model gpt-5.5`.

    No new CLI surface — `--model` already takes any tier name and the tier table does
    the rest. What has to be true is that the spawn carries the SPEC (there are no flags
    to carry) and that the pane knows where the agent's home is before codex starts.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = _git_repo(Path(self.tmp.name))
        env = mock.patch.dict(
            os.environ, {"SWITCHBOARD_MODELS_CONFIG": str(self.repo / "none.toml")})
        env.start()
        self.addCleanup(env.stop)
        self.db = store.connect(path=self.repo / "state.db")
        self.h = FakeHerdrAPI()
        self.b = Broker(self.db, self.h, repo=self.repo)

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def test_the_spawn_carries_the_spec_and_none_of_claude_s_flags(self):
        self.b.delegate("t", topic="t", role="worker", model="gpt-5.5", me="orch")
        started = self.h.started[0]
        self.assertEqual(started["model_args"], [])
        self.assertEqual(started["provider"], "codex")
        self.assertEqual(started["model"], "gpt-5.5")

    def test_the_pane_learns_the_home_before_the_agent_starts(self):
        name = self.b.delegate("t", topic="t", role="worker", model="gpt-5.5", me="orch")
        typed = " ".join(cmd for _, cmd in self.h.pane_prompts)
        self.assertIn(f"export SB_AGENT={name}", typed)
        self.assertIn(f"export CODEX_HOME=", typed)
        self.assertIn(f"codex-homes/{name}", typed)

    def test_cleanup_leaves_the_home_where_it_is(self):
        """The closing contract: *closing costs only the pane — session, summary, messages
        and transcript survive, and `sb restore` brings an agent back*. For a codex agent
        all three of those are in the home: the rollouts are the transcript, and
        `AGENTS.md` is the protocol a resumed session re-reads every turn. Deleting it
        here — which an earlier draft did, beside the prompt file — would make a
        cleaned-up codex agent unrestorable and unreadable."""
        name = self.b.delegate("t", topic="t", role="worker", model="gpt-5.5", me="orch")
        # Written by hand: the home is built inside the ADAPTER (`Herdr._codex_args`), so
        # a fake herdr never makes one. What is under test here is the teardown.
        codex.write_home(name, prompts=["p"], worktree=str(self.repo), cwd=self.repo)
        store.set_state(self.db, name, "done")
        self.b.cleanup([name])
        self.assertTrue(codex.is_codex_agent(name, self.repo))


class StartOnCodexTest(unittest.TestCase):
    """`sb start --model <tier>` — net-new plumbing, for any provider.

    `sb start` has never had a say in what the dispatcher it makes runs on: `_top` took no
    model at all, so a top was always whatever the `main` role's tier said.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = _git_repo(Path(self.tmp.name))
        env = mock.patch.dict(
            os.environ, {"SWITCHBOARD_MODELS_CONFIG": str(self.repo / "none.toml")})
        env.start()
        self.addCleanup(env.stop)
        self.db = store.connect(path=self.repo / "state.db")
        self.h = FakeHerdrAPI()
        self.h.list_agents = lambda: []
        self.h.focus = lambda n: None
        self.b = Broker(self.db, self.h, repo=self.repo)

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def test_a_top_can_be_started_on_a_codex_tier(self):
        name = self.b.start(name="general", task="do a thing", model="gpt-5.5")
        started = self.h.started[0]
        self.assertEqual(started["provider"], "codex")
        self.assertEqual(started["model_args"], [])
        # Recorded on the row, not re-derived: `restore` has only the row to work from,
        # and re-resolving the tier from the role alone is what silently dropped this
        # override on an agent's second life.
        self.assertEqual(store.get_agent(self.db, name)["tier"], "gpt-5.5")

    def test_the_workspace_is_created_with_the_environment(self):
        """A top's pane comes from `workspace create`, not from `_tab_for`, so that is
        where its environment has to be set."""
        self.b.start(name="general", task="t", model="gpt-5.5")
        env = self.h.workspace_envs[-1]
        self.assertEqual(env.get("SB_AGENT"), "general")
        self.assertTrue(env.get("CODEX_HOME", "").endswith("codex-homes/general"), env)

    def test_no_model_is_still_the_role_s_own_tier(self):
        self.b.start(name="general", task="t")
        self.assertEqual(self.h.started[0]["provider"], "claude")
        self.assertIsNone(store.get_agent(self.db, "general")["tier"])


class ModelsListingTest(unittest.TestCase):
    """`sb models` has to tell the truth about a codex tier.

    The listing shows the flags a tier reaches the provider CLI with, and a codex tier has
    none — which would print as "(provider default)", saying the exact opposite of what is
    true: it has a model and an effort, they just travel in the agent's private home.
    """

    def test_a_codex_tier_shows_its_model_and_effort_and_where_they_go(self):
        line = _models_line("gpt-5.5")
        self.assertIn("gpt-5.5", line)
        self.assertIn("medium", line)
        self.assertNotIn("(provider default)", line)

    def test_a_tier_that_really_defers_still_says_so(self):
        self.assertIn("(provider default)", _models_line("default"))


def _models_line(tier: str) -> str:
    """The one line `sb models` prints for a tier."""
    import argparse
    import contextlib
    import io
    from switchboard import cli
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli._dispatch(argparse.Namespace(cmd="models", json=False),
                      _StubBroker(None), None, None)
    return next(ln for ln in out.getvalue().splitlines() if ln.split()[:1] == [tier])


class WhoamiByNameTest(unittest.TestCase):
    """`SB_AGENT` as an identity signal.

    Better than either of the two it joins: `CLAUDE_CODE_SESSION_ID` is one provider's
    variable and codex sets no equivalent at all, and `HERDR_PANE_ID` names a pane, which
    herdr recycles once a pane closes. This names the agent.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = _git_repo(Path(self.tmp.name))
        self.db = store.connect(path=self.repo / "state.db")
        self.b = Broker(self.db, FakeHerdrAPI(), repo=self.repo)
        store.create_agent(self.db, name="w1", role="worker", pane_id="w1:p9")

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def test_an_agent_named_in_the_environment_resolves(self):
        with mock.patch.dict(os.environ, {"SB_AGENT": "w1"}, clear=True):
            self.assertEqual(self.b.whoami(), "w1")

    def test_a_name_this_store_never_heard_of_is_not_an_agent_of_ours(self):
        """Checked against the store rather than trusted. An `SB_AGENT` naming an agent
        this store has no row for is a clone's agent — which `cli._agent_caller` catches
        separately, off the same variable, and refuses."""
        with mock.patch.dict(os.environ, {"SB_AGENT": "stranger"}, clear=True):
            self.assertEqual(self.b.whoami(), HUMAN)
        from switchboard import cli
        with mock.patch.dict(os.environ, {"SB_AGENT": "stranger"}, clear=True):
            self.assertIsNotNone(cli._agent_caller(HUMAN))


if __name__ == "__main__":
    unittest.main()
