"""`sb web`: the server acts as the human, admits only its own page, and reads only linked files."""

import http.client
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from switchboard import store, web


class WebTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.checkout = Path(tmp.name).resolve() / "repo"
        self.checkout.mkdir()
        subprocess.run(["git", "init", "-q", str(self.checkout)], check=True)
        self.repo = web.Repo("repo", self.checkout / ".git", self.checkout)
        self.db = store.connect(path=self.repo.db_path)
        self.addCleanup(self.db.close)


class ChildIsTheHuman(WebTest):
    def test_a_write_from_a_server_started_in_an_agent_pane_still_runs_as_human(self):
        """Started from a herdr pane, the server inherits that pane's agent variables; the
        child `sb` must not resolve to that agent, or every answer goes out under its name."""
        store.create_agent(self.db, name="lead-x", role="lead", session_id="s-lead")
        polluted = {"SB_AGENT": "lead-x", "CLAUDE_CODE_SESSION_ID": "s-lead",
                    "CLAUDECODE": "1", "HERDR_PANE_ID": "p1"}
        with mock.patch.dict(os.environ, polluted):
            r = web.run_sb(self.repo, ["whoami", "--json"])
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["agent"], "human")


class Guard(WebTest):
    def setUp(self):
        super().setUp()
        cache = web.Cache(web.Discovery([]))
        self.server = web.Server(0, "tok", cache)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def req(self, method, path, *, host=None, headers=None, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}", **(headers or {})}
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        r.read()
        c.close()
        return r

    def test_only_the_token_holder_on_this_origin_gets_in(self):
        self.assertEqual(self.req("GET", "/api/state").status, 403)
        self.assertEqual(self.req("GET", "/?token=nope").status, 403)
        r = self.req("GET", "/?token=tok")
        self.assertEqual(r.status, 200)
        cookie = r.getheader("Set-Cookie")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        jar = {"Cookie": "sbweb=tok"}
        self.assertEqual(self.req("GET", "/api/state", headers=jar).status, 200)
        self.assertEqual(self.req("GET", "/api/state", headers=jar,
                                  host=f"evil.test:{self.port}").status, 421)
        post = {**jar, "Content-Type": "application/json"}
        self.assertEqual(self.req("POST", "/api/q/repo/1/resolve", body="{}", headers={
            **post, "Origin": "http://evil.test"}).status, 403)
        self.assertEqual(self.req("POST", "/api/q/repo/1/resolve", body="a=b", headers={
            **jar, "Origin": f"http://127.0.0.1:{self.port}",
            "Content-Type": "application/x-www-form-urlencoded"}).status, 415)


class MarkdownReader(WebTest):
    def ask_linking(self, path: Path) -> None:
        qid = store.create_question(self.db, asker="w", target="human", body="look?")
        parts = {"links": [{"title": None, "target": str(path), "kind": "file"}]}
        self.db.execute("UPDATE questions SET parts=? WHERE id=?", (json.dumps(parts), qid))
        self.db.commit()

    def test_serves_only_md_files_a_question_links_inside_the_checkout(self):
        notes = self.checkout / "notes"
        notes.mkdir()
        linked = notes / "a.md"
        linked.write_text("# hi")
        (notes / "b.md").write_text("# not linked")
        self.ask_linking(linked)
        code, body = web.read_markdown(self.repo, str(linked))
        self.assertEqual((code, body["text"]), (200, "# hi"))
        self.assertEqual(web.read_markdown(self.repo, str(notes / "b.md"))[0], 403)

        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(outside)]))
        (outside / "c.md").write_text("secret")
        (self.checkout / "via").symlink_to(outside)
        through_link = self.checkout / "via" / "c.md"
        self.ask_linking(through_link)
        self.assertEqual(web.read_markdown(self.repo, str(through_link))[0], 403)

        conf = self.checkout / ".git" / "x.md"
        conf.write_text("x")
        self.ask_linking(conf)
        self.assertEqual(web.read_markdown(self.repo, str(conf))[0], 403)


if __name__ == "__main__":
    unittest.main()
