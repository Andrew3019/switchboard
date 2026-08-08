"""The one invariant this file exists for: a schema change can never wedge a fleet.

`store.connect()` runs before every `sb` command, including the `sb done` an agent needs
in order to stop being 'live'. So anything `connect()` refuses, it refuses to the whole
machine — which is how a column split once took down seventeen agents at once, each of
them holding work and none of them able to report it.

The store-level half of this lives in `test_store.py` (degrade, defer, self-heal). These
are the CLI half: which verbs survive a degraded store, and what the refused ones say.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import cli  # noqa: E402
from switchboard import store  # noqa: E402
from switchboard.herdr import Herdr  # noqa: E402

# A NOT NULL column with no literal default: ALTER TABLE cannot add it to existing rows,
# so it is the shape that forces a rebuild. This is what splitting `workspace` in two did.
# The name has to be one the real SCHEMA does NOT carry — `branch` ships for real now, and
# a hypothetical column the store already has leaves nothing to be blocked on.
_ENDED = "    ended_at      INTEGER\n"
_SPLIT = "    ended_at      INTEGER,\n    checkout      TEXT NOT NULL\n"


class DegradedStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        for cmd in (["git", "init", "-q", "-b", "main"],
                    ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                     "commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(cmd, cwd=self.repo, capture_output=True)

        db = store.connect(self.repo)
        store.create_agent(db, name="w", role="worker")     # the live fleet
        db.close()

        self.cwd = Path.cwd()
        os.chdir(self.repo)

        original, original_hash = store.SCHEMA, store._SCHEMA_HASH
        store.SCHEMA = original.replace(_ENDED, _SPLIT)
        store._SCHEMA_HASH = hashlib.sha256(store.SCHEMA.encode()).hexdigest()[:16]
        self.addCleanup(setattr, store, "_SCHEMA_HASH", original_hash)
        self.addCleanup(setattr, store, "SCHEMA", original)
        self.addCleanup(os.chdir, self.cwd)
        self.addCleanup(self.tmp.cleanup)

        # herdr says the agent is really running, so the rebuild has to be deferred.
        alive = mock.patch.object(store, "_herdr_alive", lambda: {"w"})
        alive.start()
        self.addCleanup(alive.stop)

    def _run(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_the_store_is_degraded_not_closed(self):
        db = store.connect(self.repo)
        self.assertTrue(store.schema_deficit(db))
        self.assertIsNotNone(store.get_agent(db, "w"))       # nobody lost their state
        db.close()

    def test_a_verb_the_fleet_needs_still_runs(self):
        """The whole point. `log` reads the store and nothing else, so if the degraded
        store were still refusing at `connect()` this could not return 0."""
        code, out, err = self._run("log")
        self.assertEqual(code, 0, err)

    def test_spawning_is_refused_and_says_what_still_works(self):
        code, out, err = self._run("delegate", "do a thing")
        self.assertEqual(code, 1)                            # not 0, and not 2: the input
        self.assertIn("checkout", err)                       # was fine, the store is not
        self.assertIn("done", err)                           # what an agent can still do
        self.assertIn("--reset-store --force", err)          # and the way out, by name

    def test_refusing_a_spawn_writes_nothing(self):
        self._run("delegate", "do a thing")
        db = store.connect(self.repo)
        self.assertEqual([r["name"] for r in db.execute("SELECT name FROM agents")], ["w"])
        db.close()

    def test_doctor_is_where_a_pending_rebuild_is_visible(self):
        with mock.patch.object(Herdr, "check", lambda self: None), \
                mock.patch.object(Herdr, "version", lambda self: "0.0.0"):
            code, out, err = self._run("doctor")
        self.assertIn("PENDING REBUILD", out)
        self.assertEqual(code, 1)                            # matches the `ok` it prints


class HealthyStoreTest(unittest.TestCase):
    """The same commands, with nothing wrong — the gate must be invisible."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = store.connect(path=Path(self.tmp.name) / "state.db")
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.db.close)

    def test_no_deficit_on_a_fresh_store(self):
        self.assertEqual(store.schema_deficit(self.db), [])

    def test_every_refused_verb_is_a_real_verb(self):
        """A typo in `_NEEDS_FRESH_SCHEMA` would silently gate nothing, and the deadlock
        would come back with no test noticing."""
        parser = cli.build_parser()
        known = set(parser._subparsers._group_actions[0].choices)
        self.assertLessEqual(cli._NEEDS_FRESH_SCHEMA, known)

    def test_the_verbs_an_agent_reports_with_are_never_gated(self):
        """`done` and `block` are how an agent stops being live. If either could ever be
        refused by the schema gate, the deadlock is back."""
        for verb in ("done", "block", "inbox", "tell", "ask", "status", "doctor"):
            self.assertNotIn(verb, cli._NEEDS_FRESH_SCHEMA)


if __name__ == "__main__":
    unittest.main()
