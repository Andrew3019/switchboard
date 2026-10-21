"""`sb web`: the human's local browser page for questions and activity across every repo.

One foreground process, started by hand. It reads each repo's store read-only and never
writes to one: every write runs this checkout's `bin/sb` as a child, in the repo's main
checkout, with the agent environment removed so the caller is the human. Agent states come
from `sb status --json` run in each repo, so no repo's plugin code is loaded in here.
"""

from __future__ import annotations

import hmac
import json
import mimetypes
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

from . import codex, collector, config, output, store, usage, validate

HOST = "127.0.0.1"
COOKIE = "sbweb"
TOKEN_ENV = "SB_WEB_TOKEN"
STATUS_EVERY = 5
PR_EVERY = 30
SOURCE_EVERY = 5
SB_TIMEOUT = 60
CLOSE_TIMEOUT = 600
TRANSCRIPT_LINES = 200
MAX_BODY = 200_000
HUMAN = "human"
CHECKOUT = Path(__file__).resolve().parent.parent
SB = CHECKOUT / "bin" / "sb"
DIST = Path(__file__).resolve().parent / "web_dist"
_STORE_DIRNAME = config.setting("paths.store_dirname")


@dataclass(frozen=True)
class Repo:
    id: str
    git_dir: Path
    checkout: Path

    @property
    def db_path(self) -> Path:
        return self.git_dir / _STORE_DIRNAME / "state.db"


def child_env(*, poll: bool = False) -> dict:
    """The environment every child runs in: this one minus who we are, so `sb` sees the human."""
    env = collector.fleet_env()
    env.pop(TOKEN_ENV, None)
    if poll:
        env["SB_BOARD_POLL"] = "1"
    return env


def checkout_for(git_dir: Path) -> Optional[Path]:
    """The repo's main checkout, or None when it is not a repo the page should show."""
    db = git_dir / _STORE_DIRNAME / "state.db"
    if not db.is_file():
        return None
    where = collector._doorbell_cwd(db)
    if where is None:
        return None
    root = Path(where).resolve()
    if root in (Path("/"), Path.home().resolve()) or not root.is_dir():
        return None
    return root


class Discovery:
    """Repos from the `sb` usage log, read incrementally, plus any named with `--repo`."""

    def __init__(self, extra: list[Path]):
        self.offsets: dict[Path, int] = {}
        self.git_dirs: set[Path] = set(extra)
        self.repos: dict[str, Repo] = {}
        self.lock = threading.Lock()

    def refresh(self) -> dict[str, Repo]:
        with self.lock:
            directory = usage.usage_dir()
            for f in sorted(directory.glob("*.jsonl")) if directory.is_dir() else []:
                start = self.offsets.get(f, 0)
                try:
                    with f.open("rb") as fh:
                        fh.seek(start)
                        data = fh.read()
                except OSError:
                    continue
                end = data.rfind(b"\n") + 1
                self.offsets[f] = start + end
                for raw in data[:end].splitlines():
                    try:
                        repo = json.loads(raw).get("repo")
                    except ValueError:
                        continue
                    if repo:
                        self.git_dirs.add(Path(repo))
            found: dict[Path, Path] = {}
            for g in self.git_dirs:
                c = checkout_for(g)
                if c is not None:
                    found[g] = c
            known = {r.git_dir: r for r in self.repos.values()}
            out: dict[str, Repo] = {}
            for g in sorted(found, key=lambda g: (g not in known, str(found[g]))):
                if g in known:
                    out[known[g].id] = known[g]
                    continue
                base = validate.slug_name(found[g].name) or "repo"
                rid, n = base, 2
                while rid in out or rid in self.repos:
                    rid, n = f"{base}-{n}", n + 1
                out[rid] = Repo(rid, g, found[g])
            self.repos = out
            return dict(out)


def run_sb(repo: Repo, argv: list[str], *, timeout: float = SB_TIMEOUT,
           poll: bool = False) -> dict:
    """Run this checkout's `sb` in the repo as the human. -> {ok, result, error}."""
    try:
        p = subprocess.run([sys.executable, str(SB), *argv], cwd=str(repo.checkout),
                           env=child_env(poll=poll), capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "result": None, "error": f"sb {argv[0]} timed out"}
    try:
        result = json.loads(p.stdout) if p.stdout.strip() else None
    except ValueError:
        result = p.stdout.strip()
    err = p.stderr.strip()
    if p.returncode != 0 and not err:
        err = f"sb {argv[0]} exited {p.returncode}"
    return {"ok": p.returncode == 0, "result": result, "error": err or None}


def _git(cwd: str, *args: str) -> Optional[str]:
    try:
        p = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True,
                           timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


def _columns(db: sqlite3.Connection, table: str) -> set:
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}


def _json(text: Optional[str]) -> Any:
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def _summary(payload: Optional[str]) -> Optional[str]:
    p = _json(payload) or {}
    text = p.get("text") or p.get("summary")
    return text.split(" | verified: ")[0] if text else None


def _plans(repo: Repo) -> list[dict]:
    d = repo.git_dir / _STORE_DIRNAME / "plugins" / "plans"
    out = []
    for f in d.glob("p-*.json") if d.is_dir() else []:
        p = _json(f.read_text(errors="replace"))
        if isinstance(p, dict):
            out.append(p)
    return out


def _pr_line(pr: dict) -> dict:
    review = {"APPROVED": "approved", "CHANGES_REQUESTED": "changes requested",
              "REVIEW_REQUIRED": "review pending"}.get(pr.get("reviewDecision") or "",
                                                      "no review yet")
    checks = [c.get("conclusion") or c.get("state") or c.get("status")
              for c in pr.get("statusCheckRollup") or []]
    if not checks:
        check = None
    elif any(c in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED") for c in checks):
        check = "checks failing"
    elif all(c in ("SUCCESS", "NEUTRAL", "SKIPPED") for c in checks):
        check = "checks passing"
    else:
        check = "checks running"
    return {"number": pr.get("number"), "title": pr.get("title"), "url": pr.get("url"),
            "branch": pr.get("headRefName"), "draft": bool(pr.get("isDraft")),
            "review": review, "checks": check, "created_at": pr.get("createdAt"),
            "waiting_merge": False}


class Cache:
    """Per-repo `sb status --json` and `gh pr list`, refreshed in the background."""

    def __init__(self, discovery: Discovery):
        self.discovery = discovery
        self.status: dict[str, dict] = {}
        self.status_error: dict[str, str] = {}
        self.prs: dict[str, list[dict]] = {}
        self.pr_error: dict[str, str] = {}
        self.pr_at: dict[str, float] = {}
        self.pool = ThreadPoolExecutor(max_workers=8)

    def tick(self) -> None:
        repos = list(self.discovery.refresh().values())
        list(self.pool.map(self._status, repos))
        now = time.time()
        due = [r for r in repos if now - self.pr_at.get(r.id, 0) >= PR_EVERY]
        list(self.pool.map(self._prs, due))

    def _status(self, repo: Repo) -> None:
        r = run_sb(repo, ["status", "--json", "--all"], poll=True)
        if r["ok"] and isinstance(r["result"], dict):
            self.status[repo.id] = {a["name"]: a for a in r["result"].get("agents", [])}
            self.status_error.pop(repo.id, None)
        else:
            self.status_error[repo.id] = r["error"] or "sb status gave no JSON"

    def _prs(self, repo: Repo) -> None:
        self.pr_at[repo.id] = time.time()
        try:
            p = subprocess.run(
                ["gh", "pr", "list", "--state", "open", "--limit", "50", "--json",
                 "number,title,url,headRefName,reviewDecision,isDraft,createdAt,"
                 "statusCheckRollup"],
                cwd=str(repo.checkout), env=child_env(), capture_output=True, text=True,
                timeout=20)
        except (OSError, subprocess.TimeoutExpired) as e:
            self.pr_error[repo.id] = str(e)
            return
        if p.returncode != 0 and "none of the git remotes" in p.stderr:
            self.prs[repo.id] = []
            self.pr_error.pop(repo.id, None)
            return
        if p.returncode != 0:
            self.pr_error[repo.id] = p.stderr.strip() or "gh pr list failed"
            return
        self.prs[repo.id] = [_pr_line(x) for x in json.loads(p.stdout or "[]")]
        self.pr_error.pop(repo.id, None)

    def loop(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as e:                      # noqa: BLE001 — keep serving
                print(f"sb web: refresh failed: {e}", file=sys.stderr)
            time.sleep(STATUS_EVERY)


def latest_report(reports: list[tuple]) -> Optional[dict]:
    if not reports:
        return None
    at, agent, text = max(reports)
    return {"agent": agent, "text": text, "at": at}


def _read_repo(repo: Repo, cache: Cache) -> dict:
    """Everything the page shows for one repo, from its store and the caches."""
    db = store.connect(path=repo.db_path, readonly=True)
    try:
        agents = {r["name"]: dict(r) for r in db.execute(
            "SELECT * FROM agents ORDER BY created_at, name")}
        qcols = _columns(db, "questions")
        parts_col = ", q.parts AS parts" if "parts" in qcols else ", NULL AS parts"
        questions = [dict(r) for r in db.execute(
            f"SELECT q.id, q.asker, q.target, q.body, q.created_at, q.escalated_at{parts_col} "
            "FROM questions q JOIN agents a ON a.name = q.asker "
            "WHERE q.state = 'open' AND a.ended_at IS NULL ORDER BY q.id")]
        replied = dict(db.execute(
            "SELECT to_agent, MAX(created_at) FROM messages WHERE from_agent = ? "
            "GROUP BY to_agent", (HUMAN,)).fetchall())
        done = {r["agent"]: {"text": _summary(r["payload"]), "at": r["created_at"]}
                for r in db.execute(
                    "SELECT agent, payload, created_at FROM events WHERE id IN "
                    "(SELECT MAX(id) FROM events WHERE kind = 'done' GROUP BY agent)")}
        escalated = {}
        for q in questions:
            if q["escalated_at"]:
                row = db.execute(
                    "SELECT payload FROM events WHERE kind = 'question_escalated' "
                    "AND json_extract(payload, '$.question') = ? ORDER BY id DESC LIMIT 1",
                    (q["id"],)).fetchone()
                escalated[q["id"]] = (_json(row["payload"]) or {}).get("was") if row else None
    finally:
        db.close()

    status = cache.status.get(repo.id)
    for name, a in agents.items():
        s = (status or {}).get(name)
        a["status"] = s
        a["visible"] = (not s["closed"] and not s["archived"]) if s else a["ended_at"] is None

    children: dict[Optional[str], list[str]] = {}
    for name, a in agents.items():
        parent = a["parent"] if a["parent"] in agents else None
        children.setdefault(parent, []).append(name)
    dispatchers = {n for n in children.get(None, []) if agents[n]["role"] == "dispatcher"}
    tops = [c for d in children.get(None, []) for c in
            (children.get(d, []) if d in dispatchers else [d])]

    open_by_asker: dict[str, list[dict]] = {}
    for q in questions:
        q["parts"] = _json(q["parts"])
        q["escalated_from"] = escalated.get(q["id"])
        q["last_reply_at"] = replied.get(q["asker"])
        open_by_asker.setdefault(q["asker"], []).append(q)

    prs = cache.prs.get(repo.id, [])
    merge_branches = {p.get("branch") for p in _plans(repo)
                      if any(s.get("kind") == "merge" and s.get("progress") != "complete"
                             for s in p.get("steps", []))}
    for pr in prs:
        pr["waiting_merge"] = (pr["branch"] in merge_branches and not pr["draft"]) or \
            pr["review"] == "approved"

    def node(name: str, depth: int) -> dict:
        a = agents[name]
        s = a["status"] or {}
        asks = open_by_asker.get(name, [])
        return {
            "name": name, "parent": a["parent"], "depth": depth, "role": a["role"],
            "visible": a["visible"], "state": a["state"],
            "derived": s.get("derived_state"), "display": s.get("display_state"),
            "gone": bool(s.get("gone")), "finished": bool(s.get("finished"))
            or a["state"] == "done", "last_activity": s.get("last_activity"),
            "created_at": a["created_at"], "branch": a.get("branch"),
            "workspace": a.get("workspace"), "about": a.get("about"),
            "question": ({"id": asks[-1]["id"], "target": asks[-1]["target"],
                          "body": asks[-1]["body"], "created_at": asks[-1]["created_at"]}
                         if asks else None),
            "done": done.get(name),
        }

    trees, top_of = [], {}
    for top in tops:
        nodes: list[dict] = []

        def walk(name: str, depth: int) -> None:
            top_of[name] = top
            nodes.append(node(name, depth))
            for c in children.get(name, []):
                walk(c, depth + 1)

        walk(top, 0)
        shown = [n for n in nodes if n["visible"]]
        if not shown:
            continue
        names = {n["name"] for n in shown}
        reports = [(n["done"]["at"], n["name"], n["done"]["text"]) for n in shown
                   if n["done"] and n["done"]["text"]]
        branches = {n["branch"] or n["workspace"] for n in shown}
        trees.append({
            "top": top, "about": agents[top].get("about"),
            "created_at": agents[top]["created_at"], "nodes": shown,
            "needs_you": sum(1 for q in questions if q["asker"] in names
                             and q["target"] == HUMAN),
            "latest_report": latest_report(reports),
            "prs": [p for p in prs if p["branch"] in branches],
        })

    tree_by_top = {t["top"]: t for t in trees}
    for q in questions:
        top = top_of.get(q["asker"], q["asker"])
        q["top"] = top
        q["top_about"] = agents[top].get("about")
        q["tree"] = (tree_by_top[top]["nodes"] if top in tree_by_top
                     else [node(q["asker"], 0)])

    stuck = []
    for name, a in agents.items():
        s = a["status"]
        if not s or not a["visible"] or a["role"] == "dispatcher":
            continue
        if s.get("gone") or s.get("derived_state") == "stalled":
            stuck.append({"name": name, "gone": bool(s.get("gone")),
                          "idle": s.get("idle"), "unread": s.get("unread", 0),
                          "last_activity": s.get("last_activity")})

    return {
        "id": repo.id, "name": repo.checkout.name, "checkout": str(repo.checkout),
        "status_error": cache.status_error.get(repo.id),
        "pr_error": cache.pr_error.get(repo.id),
        "trees": trees,
        "questions": [q for q in questions if q["target"] == HUMAN],
        "between": [q for q in questions if q["target"] != HUMAN
                    and agents.get(q["target"], {}).get("ended_at") is None],
        "stuck": stuck,
        "prs": prs,
    }


def state(cache: Cache) -> dict:
    repos = []
    for repo in cache.discovery.refresh().values():
        try:
            repos.append(_read_repo(repo, cache))
        except (sqlite3.Error, OSError) as e:
            repos.append({"id": repo.id, "name": repo.checkout.name,
                          "checkout": str(repo.checkout), "error": str(e), "trees": [],
                          "questions": [], "between": [], "stuck": [], "prs": []})
    return {"now": int(time.time()), "repos": repos}


def _subtree(repo: Repo, name: str) -> list[sqlite3.Row]:
    db = store.connect(path=repo.db_path, readonly=True)
    try:
        rows = db.execute("SELECT * FROM agents").fetchall()
    finally:
        db.close()
    kids: dict[str, list] = {}
    for r in rows:
        kids.setdefault(r["parent"], []).append(r)
    out, todo = [], [r for r in rows if r["name"] == name]
    while todo:
        r = todo.pop()
        out.append(r)
        todo.extend(kids.get(r["name"], []))
    return out


def close_preview(repo: Repo, name: str, cache: Cache) -> dict:
    """What closing this tree would take with it, read from the same verb that will run."""
    dry = run_sb(repo, ["cleanup", "--json", "--force", "--dry-run", name])
    members = _subtree(repo, name)
    names = {r["name"] for r in members}
    db = store.connect(path=repo.db_path, readonly=True)
    try:
        questions = [dict(r) for r in db.execute(
            "SELECT id, asker, target, body FROM questions WHERE state = 'open'")
            if r["asker"] in names or r["target"] in names]
    finally:
        db.close()
    work = []
    for cwd in sorted({r["cwd"] for r in members if r["cwd"]}):
        if Path(cwd).resolve() == repo.checkout or not Path(cwd).is_dir():
            continue
        dirty = _git(cwd, "status", "--porcelain")
        ahead = _git(cwd, "rev-list", "--count", "HEAD", "--not", "--remotes")
        n_dirty = len(dirty.splitlines()) if dirty else 0
        n_ahead = int(ahead.strip()) if ahead and ahead.strip().isdigit() else 0
        if n_dirty or n_ahead:
            work.append({"worktree": cwd, "uncommitted": n_dirty, "unpushed": n_ahead})
    steps = [{"plan": p.get("id"), "step": s.get("id"), "owner": s.get("owner"),
              "progress": s.get("progress"), "title": s.get("display") or s.get("name")}
             for p in _plans(repo) for s in p.get("steps", [])
             if s.get("owner") in names and s.get("progress") != "complete"]
    branches = {r["branch"] or r["workspace"] for r in members}
    prs = [p for p in cache.prs.get(repo.id, []) if p["branch"] in branches]
    closing = (dry["result"] or {}).get("closed", []) if isinstance(dry["result"], dict) else []
    return {"ok": dry["ok"], "error": dry["error"], "closing": closing,
            "questions": questions, "work": work, "steps": steps, "prs": prs}


def _md_roots(repo: Repo) -> list[Path]:
    roots = [repo.checkout]
    listing = _git(str(repo.checkout), "worktree", "list", "--porcelain") or ""
    roots += [Path(line[9:]).resolve() for line in listing.splitlines()
              if line.startswith("worktree ")]
    return roots


def _linked(repo: Repo, path: str) -> bool:
    db = store.connect(path=repo.db_path, readonly=True)
    try:
        if "parts" not in _columns(db, "questions"):
            return False
        for r in db.execute("SELECT parts FROM questions WHERE parts LIKE ?",
                            (f"%{json.dumps(path)[1:-1]}%",)):
            for link in (_json(r["parts"]) or {}).get("links") or []:
                if link.get("target") == path:
                    return True
    finally:
        db.close()
    return False


def read_markdown(repo: Repo, path: str) -> tuple[int, dict]:
    p = Path(path)
    if not p.is_absolute() or p.suffix.lower() != ".md" or ".git" in p.parts:
        return 403, {"error": "only absolute .md paths outside .git"}
    if not _linked(repo, path):
        return 403, {"error": "that file is not linked from any question"}
    for parent in [p, *p.parents]:
        if parent.is_symlink():
            return 403, {"error": "a symlink in the path"}
    real = p.resolve()
    if not any(real.is_relative_to(r) for r in _md_roots(repo)):
        return 403, {"error": "outside this repo's checkouts"}
    if not real.is_file():
        return 404, {"error": "no such file"}
    return 200, {"path": path, "text": real.read_text(errors="replace"),
                 "mtime": int(real.stat().st_mtime)}


def transcript(repo: Repo, name: str) -> tuple[int, dict]:
    db = store.connect(path=repo.db_path, readonly=True)
    try:
        row = store.get_agent(db, name)
    finally:
        db.close()
    if row is None:
        return 404, {"error": f"no agent {name}"}
    path = None
    if row["session_id"]:
        path = codex.rollout_path(name, str(row["session_id"]), repo.checkout)
    if path is None:
        d = store.transcript_dir(row["cwd"])
        if d is not None and row["session_id"]:
            cand = d / f"{row['session_id']}.jsonl"
            path = cand if cand.exists() else None
    if path is None:
        return 404, {"error": "no transcript on disk for this agent"}
    return 200, {"path": str(path), "text": output.read_transcript(path, lines=TRANSCRIPT_LINES)}


def _token_ok(given: Optional[str], token: str) -> bool:
    return bool(given) and hmac.compare_digest(given, token)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, token: str, cache: Cache):
        self.token = token
        self.cache = cache
        super().__init__((HOST, port), Handler)
        bound = self.server_address[1]
        self.hosts = {f"127.0.0.1:{bound}", f"localhost:{bound}"}


class Handler(BaseHTTPRequestHandler):
    server: Server

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra: Optional[dict] = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj: Any):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _cookie(self) -> Optional[str]:
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return None

    def _guard(self) -> bool:
        host = self.headers.get("Host")
        if host not in self.server.hosts:
            self._send(421, b"wrong host", "text/plain")
            return False
        url = urllib.parse.urlsplit(self.path)
        given = urllib.parse.parse_qs(url.query).get("token", [None])[0]
        if self.command == "GET" and url.path == "/" and given is not None:
            if not _token_ok(given, self.server.token):
                self._send(403, b"wrong token", "text/plain")
                return False
            self._send(200, b'<!doctype html><meta http-equiv="refresh" content="0;url=/">',
                       "text/html", {"Set-Cookie": f"{COOKIE}={self.server.token}; "
                                                   "HttpOnly; SameSite=Strict; Path=/"})
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{host}":
            self._send(403, b"cross-origin", "text/plain")
            return False
        if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
            self._send(403, b"cross-site: open the URL that `sb web` printed", "text/plain")
            return False
        if not _token_ok(self._cookie(), self.server.token):
            self._send(403, b"Open the URL that `sb web` printed (it carries the token).",
                       "text/plain")
            return False
        return True

    def _repo(self, rid: str) -> Optional[Repo]:
        repo = self.server.cache.discovery.repos.get(rid)
        if repo is None:
            self._json(404, {"error": f"no repo {rid}"})
        return repo

    def _name(self, name: str) -> Optional[str]:
        if validate.AGENT_NAME.match(name):
            return name
        self._json(400, {"error": "not an agent name"})
        return None

    def do_GET(self):
        if not self._guard():
            return
        url = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(url.query)
        parts = [urllib.parse.unquote(p) for p in url.path.strip("/").split("/")]
        if url.path == "/api/state":
            return self._json(200, state(self.server.cache))
        if url.path == "/api/file":
            repo = self._repo(q.get("repo", [""])[0])
            if repo:
                self._json(*read_markdown(repo, q.get("path", [""])[0]))
            return
        if len(parts) == 5 and parts[:2] == ["api", "agent"] and parts[4] == "transcript":
            repo, name = self._repo(parts[2]), self._name(parts[3])
            if repo and name:
                self._json(*transcript(repo, name))
            return
        if url.path.startswith("/api/"):
            return self._json(404, {"error": "no such call"})
        self._static(url.path)

    do_HEAD = do_GET

    def _static(self, path: str):
        rel = path.lstrip("/") or "index.html"
        f = (DIST / rel).resolve()
        if not f.is_relative_to(DIST.resolve()) or not f.is_file():
            f = DIST / "index.html"
        if not f.is_file():
            return self._send(500, b"web_dist is missing: build web/ first", "text/plain")
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        self._send(200, f.read_bytes(), ctype, {
            "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline' "
            "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
            "img-src 'self' data:; frame-ancestors 'none'"})

    def do_POST(self):
        if not self._guard():
            return
        if self.headers.get("Origin") is None:
            return self._send(403, b"Origin required", "text/plain")
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            return self._json(415, {"error": "JSON only"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self._json(413, {"error": "too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._json(400, {"error": "bad JSON"})
        parts = [urllib.parse.unquote(p) for p in
                 urllib.parse.urlsplit(self.path).path.strip("/").split("/")]
        if len(parts) != 5 or parts[0] != "api":
            return self._json(404, {"error": "no such call"})
        _, kind, rid, key, verb = parts
        repo = self._repo(rid)
        if repo is None:
            return
        text = body.get("text") if isinstance(body.get("text"), str) else None
        if kind == "q" and key.isdigit() and verb in ("answer", "resolve", "escalate"):
            if verb == "answer":
                if not text or not text.strip():
                    return self._json(400, {"error": "the answer is empty"})
                return self._json(200, run_sb(repo, ["answer", "--json", key, "--", text]))
            return self._json(200, run_sb(repo, [verb, "--json", key]))
        name = self._name(key)
        if name is None:
            return
        if kind == "agent" and verb == "tell":
            if not text or not text.strip():
                return self._json(400, {"error": "the message is empty"})
            return self._json(200, run_sb(repo, ["tell", "--json", name, "--", text]))
        if kind == "agent" and verb == "focus":
            try:
                p = subprocess.run(["herdr", "agent", "focus", name], env=child_env(),
                                   capture_output=True, text=True, timeout=15)
            except (OSError, subprocess.TimeoutExpired) as e:
                return self._json(200, {"ok": False, "error": str(e)})
            return self._json(200, {"ok": p.returncode == 0,
                                    "error": (p.stderr or p.stdout).strip() or None
                                    if p.returncode else None})
        if kind == "tree" and verb == "preview":
            return self._json(200, close_preview(repo, name, self.server.cache))
        if kind == "tree" and verb == "close":
            return self._json(200, run_sb(repo, ["cleanup", "--json", "--force", name],
                                          timeout=CLOSE_TIMEOUT))
        self._json(404, {"error": "no such call"})


def _commit() -> str:
    out = _git(str(CHECKOUT), "rev-parse", "--short", "HEAD")
    return out.strip() if out else "unknown"


def _watch_source(start: Optional[str]) -> None:
    """Re-exec when this checkout's code changes, keeping the token so open tabs keep working."""
    while True:
        time.sleep(SOURCE_EVERY)
        now = collector.source_signature()
        if now and start and now != start:
            print("sb web: code changed on disk, restarting", flush=True)
            os.execv(sys.executable, sys.orig_argv)


def run(port: int, extra_repos: list[str]) -> int:
    """Serve the page until interrupted. -> exit code."""
    extra = []
    for r in extra_repos:
        try:
            extra.append(store.repo_root(Path(r).expanduser().resolve()))
        except RuntimeError as e:
            print(f"sb web: --repo {r}: {e}", file=sys.stderr)
            return 2
    token = os.environ.get(TOKEN_ENV) or secrets.token_urlsafe(24)
    os.environ[TOKEN_ENV] = token
    cache = Cache(Discovery(extra))
    try:
        server = Server(port, token, cache)
    except OSError as e:
        print(f"sb web: cannot listen on {HOST}:{port}: {e}", file=sys.stderr)
        return 1
    cache.tick()
    threading.Thread(target=cache.loop, daemon=True).start()
    threading.Thread(target=_watch_source, args=(collector.source_signature(),),
                     daemon=True).start()
    repos = ", ".join(sorted(cache.discovery.repos)) or "none yet"
    print(f"sb web: running {CHECKOUT} at {_commit()}", flush=True)
    print(f"sb web: repos: {repos}", flush=True)
    print(f"sb web: open http://{HOST}:{port}/?token={token}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
