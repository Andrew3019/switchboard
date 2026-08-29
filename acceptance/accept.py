#!/usr/bin/env python3
"""The four fleet acceptance criteria, as one command.

    ./acceptance/accept.py [branch]

Answering "does the fleet actually work?" used to cost a QA agent between twenty minutes
and an hour: stand up an isolated clone, spawn a fleet by hand, watch it, tear it down,
write it up. Phase 1 paid that five times. The answers were worth having; the method was
not. This is the method as a command.

WHAT IT CHECKS — the four criteria phase 1 was judged against, and the ones every later
phase needs too:

  1. A cold fan-out really starts. Six agents into six brand-new checkouts; all six take
     their task and report; and no spawn is misreported in EITHER direction — neither a
     success for an agent that got nothing nor a failure for an agent that is working.
  2. A child's report wakes its parent by itself, delivered by the collector's doorbell,
     with no command run by anyone and no heartbeat. Forced onto the DEFERRED path on
     purpose: the child reports while the parent is mid-turn, so the direct ring cannot
     happen and only the doorbell can deliver. Runs 2 and 3 both failed to isolate this.
  3. A blocked agent stays blocked while a sibling mails it, and is released by the
     human's answer, which it can then read.
  4. A cleanup sweep that refuses something says so — including when it also closed
     something, which is the case that was silent through runs 2, 3 and 4 (§5).

HOW IT STAYS OUT OF THE LIVE FLEET. Every check runs in its own throwaway `git clone` of
the repo, checked out at the branch under test, driven through THAT clone's own `./bin/sb`:
a clone has its own `.git`, so `git rev-parse --git-common-dir` resolves to its own
`state.db` and the live store is never opened. The sharp edge that clone does NOT fix is
herdr: there is one herdr daemon per machine and agent names are global across
otherwise-isolated stores, so every name here carries a random run id (`sba1b2c3-w1`) that cannot collide with a live agent.

WHAT IT LEAVES BEHIND: nothing. Agents, herdr workspaces, worktrees and the clones are
all torn down on success, on failure, and on Ctrl-C. Never an unscoped `pkill`: agents are
closed through `sb cleanup`, workspaces through `herdr workspace close <id>` selected by
their checkout path AND refused unless every path herdr reports for them is inside this
run's own directories (`workspace_is_ours` — herdr closes a whole worktree family when
asked to close a repo's primary checkout), and the one process closed by pid is each
clone's own collector,
whose pid this script read out of that clone's own snapshot and verified before signalling.

Logs and the raw evidence for every check are written to a run directory that SURVIVES the
teardown; the path is printed at the end. This is not a pytest test and must not join the
suite — see `acceptance/README.md`.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import signal
import sqlite3
import string
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# Deadlines. The rule is the smallest run that distinguishes working from broken: no
# endurance runs and no multi-minute holds. Every number here is "how long before a fleet
# that works would have finished", with room for one delivery re-send (~30 s each).
SPAWN_S = 240.0          # a delegate, plus the agent taking its task and reporting
DOORBELL_S = 240.0       # a delegate by the parent + a 60 s turn + a ring + the reply
BLOCK_S = 240.0
SWEEP_S = 240.0
HOLD_S = 15.0            # how long a block is watched holding against a sibling's message
POLL_S = 3.0

STAMP = "%H:%M:%S"


# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------


def now() -> float:
    return time.time()


def hms(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}m{seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


class Log:
    """One append-only file for the whole run, plus stdout for the headlines.

    Everything a failed check would need to be argued about goes in the file; stdout
    stays at the ten-second level the brief asked for.
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = self.path.open("a", buffering=1)

    def write(self, tag: str, text: str) -> None:
        with self._lock:
            for line in str(text).splitlines() or [""]:
                self.fh.write(f"{time.strftime(STAMP)} [{tag}] {line}\n")

    def say(self, text: str = "") -> None:
        print(text, flush=True)
        self.write("out", text)


@dataclass
class Run:
    rc: int
    out: str
    err: str

    @property
    def text(self) -> str:
        return (self.out + ("\n" + self.err if self.err else "")).strip()

    def json(self) -> Optional[dict]:
        try:
            return json.loads(self.out)
        except Exception:
            return None


def sh(args: list[str], cwd: Optional[Path] = None, timeout: float = 120.0) -> Run:
    try:
        p = subprocess.run([str(a) for a in args], cwd=str(cwd) if cwd else None,
                           capture_output=True, text=True, timeout=timeout)
        return Run(p.returncode, p.stdout, p.stderr)
    except subprocess.TimeoutExpired as e:
        return Run(124, e.stdout or "", f"timed out after {timeout}s")
    except OSError as e:
        return Run(127, "", str(e))


def herdr_call(*args: str) -> Optional[dict]:
    r = sh(["herdr", *args], timeout=60.0)
    try:
        return json.loads(r.out).get("result")
    except Exception:
        return None


def workspace_is_ours(wt: dict, roots: list[Path]) -> bool:
    """Is this herdr workspace provably one of ours — every path it names inside `roots`?

    `herdr workspace close <id>` is not the single-workspace operation its name promises.
    herdr groups a repo's primary checkout with every `git worktree` of it under one key
    (the shared `.git`), and closing the primary closes the WHOLE group in one call — which
    is how one hand-typed close took the live fleet down on 2026-08-16 (see
    `notes/herdr-close-mechanism.md`). A clone is its own repository, so its key cannot
    collide with the live fleet's; this function is what makes that an enforced fact rather
    than an assumption. It answers False unless every path herdr reports for the workspace
    is at or under a directory this run created — no path at all, one path outside, or an
    unresolvable path all refuse.
    """
    real_roots = [Path(os.path.realpath(r)) for r in roots]
    paths = [p for p in (wt.get("repo_root"), wt.get("checkout_path")) if p]
    if not paths:
        return False
    for p in paths:
        try:
            here = Path(os.path.realpath(str(p)))
        except OSError:
            return False
        if not any(here == root or root in here.parents for root in real_roots):
            return False
    return True


# ---------------------------------------------------------------------------
# the isolated instance
# ---------------------------------------------------------------------------


class Clone:
    """One throwaway clone of the repo, and everything that has to be undone about it."""

    def __init__(self, source: Path, root: Path, name: str, branch: str, log: Log):
        self.source, self.root, self.name = source, root, name
        self.branch, self.log = branch, log
        self.path = root / name
        self.torn_down = False

    # -- setup ------------------------------------------------------------

    def create(self) -> None:
        r = sh(["git", "clone", "--quiet", str(self.source), str(self.path)], timeout=300.0)
        if r.rc != 0:
            raise RuntimeError(f"git clone failed: {r.text}")
        r = sh(["git", "checkout", "--quiet", self.branch], cwd=self.path, timeout=120.0)
        if r.rc != 0:
            raise RuntimeError(f"git checkout {self.branch} failed: {r.text}")
        self.head = sh(["git", "rev-parse", "--short", "HEAD"], cwd=self.path).out.strip()
        # Prove the isolation rather than assuming it: this clone's own store, and not one
        # row in it. Both halves of the isolation method, re-checked every run.
        doctor = self.sb("doctor")
        store_line = next((l for l in doctor.text.splitlines() if l.startswith("store")), "")
        if str(self.path) not in store_line:
            raise RuntimeError(f"clone is not on its own store: {store_line!r}")
        status = self.sb("status", "--all", "--json").json() or {}
        if status.get("agents"):
            raise RuntimeError("fresh clone already has agents — not an isolated store")
        self.log.write(self.name, f"clone {self.path} @ {self.branch} {self.head}")
        self.log.write(self.name, store_line)

    # -- talking to it ----------------------------------------------------

    def sb(self, *args: str, timeout: float = 300.0) -> Run:
        r = sh([str(self.path / "bin" / "sb"), *args], cwd=self.path, timeout=timeout)
        self.log.write(self.name, f"$ sb {' '.join(args)}  -> rc={r.rc}\n{r.text}")
        return r

    def status(self) -> dict:
        # `--all`: acceptance verifies OUTCOMES, and most of them are finished agents — a
        # child that reached `done`, a blocker that closed. `sb status` now defaults to the
        # working set (finished rows dropped), which is right for a board and wrong for a
        # harness whose checks are almost all `state == "done"`. This one reader wants the
        # whole tree, so it asks for it.
        return self.sb("status", "--all", "--json", timeout=120.0).json() or {"agents": []}

    def agent(self, name: str) -> Optional[dict]:
        return next((a for a in self.status().get("agents", []) if a["name"] == name), None)

    # -- reading it WITHOUT running `sb` ----------------------------------
    #
    # Check 2 measures a delivery that must be made by nothing but the doorbell, and every
    # `sb` command flushes pending mail at startup (`cli.main` -> `flush_pending`). So the
    # store is read read-only, straight from sqlite, exactly as acceptance run 4 did.

    @property
    def db_path(self) -> Path:
        return self.path / ".git" / "agentflow" / "state.db"

    def query(self, sql: str, args: tuple = ()) -> list[dict]:
        uri = f"file:{self.db_path}?mode=ro"
        db = sqlite3.connect(uri, uri=True, timeout=10.0)
        try:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute(sql, args).fetchall()]
        finally:
            db.close()

    def reported(self, name: str) -> Optional[str]:
        """What an agent said when it finished, read without running `sb`.

        `agents` has no summary column — an end is a `done` event with the text in its
        payload, and a message to the parent. The event is the one that exists whether or
        not the agent had a parent.
        """
        rows = self.query("SELECT payload FROM events WHERE agent=? AND kind='done' "
                          "ORDER BY id DESC LIMIT 1", (name,))
        if not rows:
            return None
        try:
            return (json.loads(rows[0]["payload"] or "{}") or {}).get("summary")
        except Exception:
            return None

    def snapshot(self) -> dict:
        """The collector's published counters — `doorbells`, `last_doorbell`, errors."""
        try:
            raw = json.loads((self.path / ".git" / "agentflow" / "panel"
                              / "snapshot.json").read_text())
        except Exception:
            return {}
        return raw.get("collector") or raw.get("state") or {}

    # -- teardown ---------------------------------------------------------

    def teardown(self) -> None:
        """Close everything this clone caused, in the order that leaves nothing behind.

        Agents first (through `sb`, by name, so herdr's own bookkeeping is done for us),
        then any workspace herdr still holds for this clone, then the collector this
        clone's board elected, then the directories. Every step is best-effort and none of
        them can reach anything outside this clone: workspaces are selected by checkout
        path, and the only pid signalled is one this clone published as its own.
        """
        if self.torn_down:
            return
        self.torn_down = True
        try:
            self._close_agents()
        except Exception as e:                                        # noqa: BLE001
            self.log.write(self.name, f"teardown: closing agents failed: {e}")
        try:
            self._close_workspaces()
        except Exception as e:                                        # noqa: BLE001
            self.log.write(self.name, f"teardown: closing workspaces failed: {e}")
        try:
            self._stop_collector()
        except Exception as e:                                        # noqa: BLE001
            self.log.write(self.name, f"teardown: stopping collector failed: {e}")
        for d in (Path.home() / ".herdr" / "worktrees" / self.name, self.path):
            shutil.rmtree(d, ignore_errors=True)
        self.log.write(self.name, "teardown: done")

    def _close_agents(self) -> None:
        for _ in range(3):
            # `alive`, not merely present: a closed agent keeps its row forever, so
            # sweeping on the row would loop on agents that are already gone.
            names = [a["name"] for a in self.status().get("agents", []) if a.get("alive")]
            if not names:
                return
            self.sb("cleanup", *names, "--force", timeout=300.0)
        left = [a["name"] for a in self.status().get("agents", []) if a.get("alive")]
        if left:
            self.log.write(self.name, f"teardown: STILL OPEN after 3 sweeps: {left}")

    def _close_workspaces(self) -> None:
        res = herdr_call("workspace", "list") or {}
        mine = str(self.path)
        home = str(Path.home() / ".herdr" / "worktrees" / self.name)
        roots = [self.path, Path(home)]
        for w in res.get("workspaces", []):
            wt = w.get("worktree") or {}
            paths = f"{wt.get('repo_root', '')}|{wt.get('checkout_path', '')}"
            if mine in paths or home in paths:
                # The substring match above SELECTS; this check AUTHORISES, and nothing is
                # closed without it. A herdr close can take every workspace sharing the
                # repo's `.git` with it, so "looks like ours" is not good enough to spend.
                if not workspace_is_ours(wt, roots):
                    self.log.write(self.name, f"teardown: REFUSING to close "
                                              f"{w['workspace_id']} ({w.get('label')}): "
                                              f"{paths} is not under {roots} — left open")
                    continue
                self.log.write(self.name, f"teardown: herdr workspace close "
                                          f"{w['workspace_id']} ({w.get('label')})")
                herdr_call("workspace", "close", w["workspace_id"])

    def _stop_collector(self) -> None:
        """SIGTERM this clone's own collector — by a pid it published, checked first.

        It would retire by itself within a minute of the last panel closing, but the clone
        directory is about to be deleted and `panel.publish` would recreate the tree it
        writes into. The pid comes out of this clone's snapshot and is verified to be a
        `switchboard.collector` before anything is signalled, so this cannot reach another
        clone's collector, the live fleet's, or any other process on the machine.
        """
        pid = (self.snapshot() or {}).get("pid")
        if not isinstance(pid, int):
            return
        cmd = sh(["ps", "-o", "command=", "-p", str(pid)]).out
        if "switchboard.collector" not in cmd:
            self.log.write(self.name, f"teardown: pid {pid} is not our collector, left alone")
            return
        self.log.write(self.name, f"teardown: SIGTERM collector pid {pid}")
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------


@dataclass
class Check:
    n: int
    title: str
    ok: Optional[bool] = None
    headline: str = ""
    notes: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def verdict(self) -> str:
        return "PASS" if self.ok else ("FAIL" if self.ok is False else "ERROR")


def wait_until(fn: Callable[[], Optional[object]], deadline: float,
               poll: float = POLL_S) -> Optional[object]:
    """Poll until `fn` returns something truthy, or the deadline passes. -> that, or None."""
    while now() < deadline:
        got = fn()
        if got:
            return got
        time.sleep(poll)
    return fn() or None


# ---------------------------------------------------------------------------
# check 1 — a cold fan-out really starts
# ---------------------------------------------------------------------------


def _why(r: Run) -> str:
    """The line of an `sb` failure that says what went wrong, not the first line it printed.

    A delegate prints notices before its error (`forked from 'x' — your branch`), so the
    first line is usually the least interesting thing in the output.
    """
    lines = [l for l in r.text.splitlines() if l.strip()]
    return next((l for l in lines if l.startswith("sb:") and "[" in l),
                lines[-1] if lines else "")


def spawned(topic: str, role: str = "worker") -> str:
    """What an agent passed `--name <topic>` is actually CALLED.

    Since agents became `<role>-<topic>` (`Broker._compose_name`), `--name` names the
    SUBJECT and the role goes in front of it, so this script can no longer look a spawn up
    by the string it passed. Mirrored here rather than read back out of the `--json`,
    because two of the spawns below are made by an agent inside the fleet and this script
    only ever sees their rows. Every topic here is unique to the run id, so the
    collision suffix `_compose_name` would add cannot fire.
    """
    return f"{role}-{topic}"


def check_fanout(clone: Clone, rid: str, log: Log) -> Check:
    c = Check(1, "a cold fan-out of six starts six")
    t0 = now()
    token = f"FANOUT-{rid}"
    topics = [f"{rid}-w{i}" for i in range(1, 7)]
    names = [spawned(t) for t in topics]
    spawns: dict[str, Run] = {}

    def spawn(i: int, topic: str) -> None:
        name = spawned(topic)
        task = (f"Your entire job is one command. Run it now, as your first action: "
                f"sb done \"{token} {name}\" — do not read any file, do not explore, "
                f"do not run anything else.")
        spawns[name] = clone.sb("delegate", task, "--name", topic, "--json",
                                timeout=SPAWN_S)

    # All six at once, which is the load the criterion is about — a lead handing out six
    # tasks in one breath — and the shape under which a real spawn defect showed up at 2
    # in 42 during phase 1. Issuing them one at a time hides that.
    #
    # This was sequential for a while because six simultaneous `sb delegate`s in one
    # checkout raced in `git worktree add` ("could not lock config file .git/config: File
    # exists") and one of them died `fork_failed`. That race is fixed on main — an flock
    # around worktree creation, `Broker._fork_lock` — so the concurrent shape now measures
    # the spawn path rather than that bug. The clone's store is already warm here (`create`
    # runs `sb doctor` and `sb status`), which keeps this off the separate first-touch
    # schema-creation collision found alongside it.
    threads = [threading.Thread(target=spawn, args=(i, t))
               for i, t in enumerate(topics, 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    deadline = now() + SPAWN_S

    def reported() -> Optional[list]:
        rows = {a["name"]: a for a in clone.status().get("agents", [])}
        got = [n for n in names
               if token in ((rows.get(n) or {}).get("summary") or "")
               and (rows.get(n) or {}).get("state") == "done"]
        return got if len(got) == len(names) else None

    wait_until(reported, deadline)
    rows = {a["name"]: a for a in clone.status().get("agents", [])}
    took = {n for n in names if token in ((rows.get(n) or {}).get("summary") or "")}
    claimed = {n for n in names if spawns.get(n) and spawns[n].rc == 0}
    false_success = sorted(claimed - took)
    false_failure = sorted(took - claimed)
    checkouts = {(rows.get(n) or {}).get("workspace") for n in took}

    c.seconds = now() - t0
    c.notes.append(f"delegate exit codes: " +
                   ", ".join(f"{n}={spawns[n].rc}" for n in names if n in spawns))
    c.notes.append(f"reported with their token: {len(took)}/6 — {sorted(took)}")
    c.notes.append(f"distinct checkouts: {len(checkouts - {None})}")
    if false_success:
        c.notes.append(f"REPORTED SUCCESS FOR AGENTS THAT NEVER TOOK THE TASK: {false_success}")
    if false_failure:
        for n in false_failure:
            c.notes.append(f"REPORTED FAILURE FOR A WORKING AGENT: {n} — "
                           f"{_why(spawns[n])}")
    missing = sorted(set(names) - took)
    if missing:
        c.notes.append(f"never reported: {missing}")

    c.ok = (len(took) == 6 and not false_success and not false_failure
            and len(checkouts - {None}) == 6)
    c.headline = (f"6/6 took their task and reported into 6 new checkouts, "
                  f"0 spawns misreported" if c.ok else
                  f"{len(took)}/6 reported; {len(false_success)} false success, "
                  f"{len(false_failure)} false failure")
    return c


# ---------------------------------------------------------------------------
# check 2 — a child's report wakes its parent, by the doorbell alone
# ---------------------------------------------------------------------------


def check_doorbell(clone: Clone, rid: str, log: Log) -> Check:
    c = Check(2, "a child's report wakes its parent")
    t0 = now()
    ptopic, ctopic = f"{rid}-p", f"{rid}-c"
    parent, child = spawned(ptopic, "lead"), spawned(ctopic)
    ctok = f"CHILD-{rid}"

    # THE DEFERRED PATH, FORCED, and forced by shell rather than by asking an agent to be
    # punctual. The parent's delegate and its long turn are ONE command joined by `&&`, so
    # from the moment the child exists until 45 s after it was confirmed, the parent is
    # inside a single tool call and herdr has it `working` — which is exactly the state
    # `_ring` defers on. An earlier version asked the parent for two commands in order and
    # measured the direct ring instead: the parent's turn had ended before its child got
    # round to reporting, which is the same reason runs 2 and 3 never isolated this.
    child_task = f'Run this one command and nothing else: sb done "{ctok}"'
    parent_task = (
        f"Do exactly this and nothing else. FIRST, run this as ONE single shell command: "
        f"sb delegate '{child_task}' --name {ctopic} && sleep 45 . "
        f"THEN stop: run no command at all, call no tool, end your turn and wait quietly. "
        f"LATER, only if you are told that you have mail, run: sb inbox — and then finish "
        f"by running: sb done \"WOKEN <paste here the exact text of what you read>\"")

    # `--role lead` because the parent's whole job here is to delegate, and since
    # phase 5 a role without delegate rights is refused outright. Left at the default
    # (`worker`) this check failed with the parent's own `sb delegate` refused, which reads
    # as "the child never reported" and is not what it is measuring.
    spawn = clone.sb("delegate", parent_task, "--name", ptopic, "--role", "lead",
                     "--json", timeout=SPAWN_S)
    if spawn.rc != 0:
        c.ok, c.seconds = False, now() - t0
        c.headline = "the parent could not be spawned"
        c.notes.append(spawn.text)
        return c

    # From here on this clone gets NO `sb` command from this script: every one of them
    # would flush the mail itself and the measurement would be about this script, not the
    # doorbell. Everything below is read-only sqlite and the collector's own snapshot.
    deadline = now() + DOORBELL_S

    def the_message() -> Optional[dict]:
        rows = clone.query("SELECT * FROM messages WHERE from_agent=? AND to_agent=?",
                           (child, parent))
        return rows[0] if rows else None

    msg = wait_until(the_message, deadline)
    if not msg:
        c.ok, c.seconds = False, now() - t0
        c.headline = "the child never reported to its parent"
        c.notes.append(f"agents: {clone.query('SELECT name,state FROM agents')}")
        return c

    deferred = clone.query("SELECT * FROM events WHERE agent=? AND kind='ring_deferred'",
                           (parent,))
    at_rest = msg["delivered_at"] is None
    bells_before = (clone.snapshot() or {}).get("doorbells")

    def delivered() -> Optional[dict]:
        m = the_message()
        return m if m and m["delivered_at"] else None

    got = wait_until(delivered, deadline)
    snap = clone.snapshot() or {}
    bells_after, last_bell = snap.get("doorbells"), snap.get("last_doorbell")

    def woken() -> Optional[str]:
        rows = clone.query("SELECT state FROM agents WHERE name=?", (parent,))
        return clone.reported(parent) if rows and rows[0]["state"] == "done" else None

    summary = wait_until(woken, deadline) or ""

    c.seconds = now() - t0
    lag = (got["delivered_at"] - got["created_at"]) if got else None
    c.notes.append(f"child reported at {msg['created_at']}, delivered_at="
                   f"{got['delivered_at'] if got else None} (lag {lag}s)")
    c.notes.append(f"ring_deferred events for the parent: {len(deferred)}")
    c.notes.append("the parent's events: " + ", ".join(
        f"{e['created_at']} {e['kind']}" for e in
        clone.query("SELECT created_at,kind FROM events WHERE agent=? ORDER BY id", (parent,))))
    c.notes.append(f"collector doorbells {bells_before} -> {bells_after}, "
                   f"last at {last_bell}, error={snap.get('doorbell_error')}")
    c.notes.append(f"parent summary: {summary[:200]!r}")
    c.notes.append("no `sb` command was run by this script in this clone between the "
                   "child's report and the delivery")

    bell_rang = (isinstance(bells_after, int) and isinstance(bells_before, int)
                 and bells_after > bells_before)
    near_a_bell = (got is not None and isinstance(last_bell, (int, float))
                   and got["delivered_at"] <= last_bell + 5)
    if not deferred or not at_rest:
        c.ok = False
        c.headline = ("the report was delivered directly, so the doorbell was never the "
                      "thing that woke the parent — this run did not test it")
    elif not got:
        c.ok = False
        c.headline = "the report was deferred and then never delivered at all"
    elif not (bell_rang or near_a_bell):
        c.ok = False
        c.headline = "it was delivered, but not by a doorbell this script can account for"
    elif ctok not in summary:
        c.ok = False
        c.headline = "the parent was rung but never read or reported what its child said"
    else:
        c.ok = True
        c.headline = (f"deferred while the parent worked, then delivered by the doorbell "
                      f"{lag}s later; the parent woke and read it")
    return c


# ---------------------------------------------------------------------------
# check 3 — a block holds against a sibling, and yields to the human
# ---------------------------------------------------------------------------


def check_block(clone: Clone, rid: str, log: Log) -> Check:
    c = Check(3, "a block holds until the human answers")
    t0 = now()
    btopic, stopic = f"{rid}-b", f"{rid}-s"
    blocker, sibling = spawned(btopic), spawned(stopic)
    sib_tok, human_tok = f"SIBLING-{rid}", f"HUMAN-ANSWER-{rid}"

    btask = (f"Run this exact command immediately and as your only action: "
             f"sb block \"acceptance probe {rid}\" . "
             f"Later, when the human has answered you, run: sb inbox — and then finish by "
             f"running: sb done \"READ <paste here the exact text of every message you "
             f"read>\". Do nothing else at any point.")
    spawn = clone.sb("delegate", btask, "--name", btopic, "--json", timeout=SPAWN_S)
    if spawn.rc != 0:
        c.ok, c.seconds, c.headline = False, now() - t0, "the agent could not be spawned"
        c.notes.append(spawn.text)
        return c

    deadline = now() + BLOCK_S
    if not wait_until(lambda: (clone.agent(blocker) or {}).get("blocked"), deadline):
        c.ok, c.seconds, c.headline = False, now() - t0, "the agent never blocked"
        c.notes.append(str(clone.agent(blocker)))
        return c
    blocked_at = now()

    stask = (f"Run these two commands and nothing else: first "
             f"sb tell {blocker} \"{sib_tok}\" , then sb done \"sent\".")
    clone.sb("delegate", stask, "--name", stopic, "--json", timeout=SPAWN_S)
    sent = wait_until(lambda: clone.query(
        "SELECT * FROM messages WHERE from_agent=? AND to_agent=?", (sibling, blocker)),
        deadline)
    if not sent:
        c.ok, c.seconds, c.headline = False, now() - t0, "the sibling never sent its message"
        return c

    # Watch it hold. Short on purpose — the criterion is that a sibling cannot lift a
    # block, and that is decided in the first seconds, not by an endurance run.
    held_until = now() + HOLD_S
    broke = None
    while now() < held_until:
        a = clone.agent(blocker) or {}
        m = clone.query("SELECT * FROM messages WHERE id=?", (sent[0]["id"],))[0]
        if not a.get("blocked"):
            broke = f"the block lifted on its own after {int(now() - blocked_at)}s"
            break
        if m["delivered_at"] or m["read_at"]:
            broke = "the sibling's message was delivered to a blocked agent"
            break
        time.sleep(POLL_S)
    held = now() - blocked_at
    held_events = clone.query(
        "SELECT COUNT(*) n FROM events WHERE agent=? AND kind='ring_held'", (blocker,))
    c.notes.append(f"watched for {int(held)}s after it blocked, with the sibling's "
                   f"message sent; ring_held events: {held_events[0]['n']}")
    if broke:
        c.ok, c.seconds, c.headline = False, now() - t0, broke
        return c

    # The human's answer. This script has no agent row in this clone's store, so `sb`
    # resolves it as HUMAN — this is the real answer path, not a simulation of it.
    answer = clone.sb("tell", blocker, human_tok, timeout=120.0)
    c.notes.append(f"human answer sent: rc={answer.rc} {answer.text.splitlines()[:1]}")

    def finished() -> Optional[dict]:
        a = clone.agent(blocker) or {}
        return a if a.get("state") == "done" else None

    end = wait_until(finished, deadline)
    summary = (end or {}).get("summary") or ""
    c.seconds = now() - t0
    c.notes.append(f"blocker summary: {summary[:300]!r}")
    read_human = human_tok in summary
    read_sib = sib_tok in summary
    if not end:
        c.ok, c.headline = False, "the human's answer did not release the block"
    elif not read_human:
        c.ok, c.headline = False, ("it unblocked but never reported reading the human's "
                                   "answer")
    else:
        c.ok = True
        c.headline = (f"held {int(held)}s against a sibling, released by the human's "
                      f"answer and read it" + ("" if read_sib else
                                               " (the sibling's held message was not quoted back)"))
    return c


# ---------------------------------------------------------------------------
# check 4 — a sweep that refuses something says so
# ---------------------------------------------------------------------------


def check_sweep(clone: Clone, rid: str, log: Log) -> Check:
    c = Check(4, "a sweep names what it refused")
    t0 = now()
    dtopic, ktopic = f"{rid}-d", f"{rid}-k"
    closable, refused = spawned(dtopic), spawned(ktopic)

    dtask = (f"Your entire job is one command. Run it now: sb done \"done {rid}\" — "
             f"nothing else.")
    ktask = (f"Run this exact command immediately and as your only action: "
             f"sb block \"acceptance probe {rid} — stay blocked\" . Then do nothing "
             f"whatsoever, whatever anyone says.")
    # Sequential — see the note in `check_fanout` about two forks racing in one checkout.
    for task, topic in ((dtask, dtopic), (ktask, ktopic)):
        r = clone.sb("delegate", task, "--name", topic, "--json", timeout=SPAWN_S)
        if r.rc != 0:
            c.ok, c.seconds = False, now() - t0
            c.headline = f"could not spawn {spawned(topic)} to set the sweep up"
            c.notes.append(r.text)
            return c

    deadline = now() + SPAWN_S

    def ready() -> Optional[bool]:
        rows = {a["name"]: a for a in clone.status().get("agents", [])}
        return bool((rows.get(closable) or {}).get("state") == "done"
                    and (rows.get(refused) or {}).get("blocked"))

    if not wait_until(ready, deadline):
        c.ok, c.seconds = False, now() - t0
        c.headline = "could not set up a sweep with one closable and one refusable agent"
        c.notes.append(str(clone.status().get("agents")))
        return c

    dry = clone.sb("cleanup", "--dry-run", timeout=180.0)
    sweep = clone.sb("cleanup", timeout=300.0)
    asjson = clone.sb("cleanup", "--json", timeout=180.0).json() or {}

    c.seconds = now() - t0
    c.notes.append(f"sweep said:\n{sweep.text}")
    c.notes.append(f"--dry-run said:\n{dry.text}")
    c.notes.append(f"a second sweep, --json: {json.dumps(asjson)[:400]}")

    closed_line = next((l for l in sweep.text.splitlines() if l.startswith("closed:")), "")
    said_closed = closable in closed_line
    named_refusal = re.search(rf"^\s*(?!closed:).*\b{re.escape(refused)}\b.*\S",
                              sweep.text, re.M) is not None
    c.notes.append(f"closed line named the finished agent: {said_closed}; "
                   f"the refused agent was named with a reason: {named_refusal}")
    if not said_closed:
        c.ok, c.headline = False, "the sweep closed nothing, so nothing was being hidden"
    elif not named_refusal:
        c.ok, c.headline = False, (f"it closed {closable} and said nothing at all about "
                                   f"{refused}, which it refused")
    else:
        reason = next((l.strip() for l in sweep.text.splitlines() if refused in l
                       and not l.startswith("closed:")), "")
        c.ok = True
        c.headline = f"closed 1, refused 1 and said why: {reason[:80]!r}"
    if dry.text and refused not in dry.text:
        c.notes.append("NOTE (not part of the criterion): --dry-run did not mention the "
                       "refusal it would make")
    return c


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------


CHECKS = {1: ("a cold fan-out of six starts six", check_fanout),
          2: ("a child's report wakes its parent", check_doorbell),
          3: ("a block holds until the human answers", check_block),
          4: ("a sweep names what it refused", check_sweep)}


class Session:
    def __init__(self, args) -> None:
        self.args = args
        self.rid = "sb" + "".join(random.choice(string.ascii_lowercase + string.digits)
                                  for _ in range(6))
        self.dir = Path(args.workdir or (os.environ.get("TMPDIR") or "/tmp")) / f"accept-{self.rid}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log = Log(self.dir / "run.log")
        self.clones: list[Clone] = []
        self._lock = threading.Lock()
        self.results: dict[int, Check] = {}

    def clone_for(self, tag: str) -> Clone:
        # The clone's directory name is also its herdr workspace label and the directory
        # its agents' worktrees land in (`~/.herdr/worktrees/<name>`), so it carries the
        # run id for the same reason the agent names do.
        c = Clone(Path(self.args.repo), self.dir, tag, self.args.branch, self.log)
        with self._lock:
            self.clones.append(c)
        c.create()
        return c

    def teardown(self) -> None:
        for c in list(self.clones):
            try:
                c.teardown()
            except Exception as e:                                    # noqa: BLE001
                self.log.write("teardown", f"{c.name}: {e}")

    def run_check(self, n: int) -> None:
        tag, fn = CHECKS[n]
        clone = None
        # Every agent name carries the run id, and the run id is random: herdr's name
        # space is one per machine and is the one thing a clone does not isolate.
        rid = f"{self.rid}{n}"
        try:
            clone = self.clone_for(rid)
            check = fn(clone, rid, self.log)
        except Exception as e:                                        # noqa: BLE001
            check = Check(n, CHECKS[n][0], ok=None, headline=f"the check itself broke: {e}")
        finally:
            if clone is not None and not self.args.keep:
                clone.teardown()
        self.results[n] = check
        self.log.write("check", f"{n} {check.verdict()} {check.headline}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run the four fleet acceptance criteria against a branch, in "
                    "throwaway clones, and say pass or fail with the number behind it.")
    ap.add_argument("branch", nargs="?", help="branch to test (default: what is checked "
                                              "out where this script lives)")
    ap.add_argument("--repo", default=str(REPO), help="repo to clone (default: this one)")
    ap.add_argument("--only", help="comma-separated check numbers, e.g. --only 1,4")
    ap.add_argument("--serial", action="store_true",
                    help="run the checks one at a time instead of together")
    ap.add_argument("--keep", action="store_true",
                    help="LEAKS A FLEET: leave the clones and their agents running")
    ap.add_argument("--workdir", help="where clones and logs go (default: $TMPDIR)")
    args = ap.parse_args(argv)

    if not args.branch:
        args.branch = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                         cwd=Path(args.repo)).out.strip() or "main"
    wanted = sorted({int(x) for x in args.only.split(",")} if args.only else CHECKS)

    s = Session(args)
    started = now()
    s.log.say(f"switchboard fleet acceptance — branch {args.branch}, "
              f"cloned from {args.repo}")
    s.log.say(f"run {s.rid} — logs and evidence: {s.dir}")
    s.log.say("")

    def bail(_sig=None, _frm=None):
        s.log.say("\ninterrupted — tearing down")
        s.teardown()
        os._exit(130)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, bail)

    try:
        if args.serial:
            for n in wanted:
                s.run_check(n)
        else:
            ts = [threading.Thread(target=s.run_check, args=(n,)) for n in wanted]
            for t in ts:
                t.start()
                time.sleep(2.0)          # stagger the clones, not the checks
            for t in ts:
                t.join()
    finally:
        if not args.keep:
            s.teardown()

    failed = 0
    for n in wanted:
        c = s.results.get(n) or Check(n, CHECKS[n][0], ok=None, headline="did not run")
        failed += 0 if c.ok else 1
        s.log.say(f"  {n}  {c.title:40.40} {c.verdict():5}  {c.headline}"
                  f"   [{hms(c.seconds)}]")
    s.log.say("")
    for n in wanted:
        c = s.results.get(n)
        if c and not c.ok:
            s.log.say(f"  check {n} — {c.title}")
            for line in c.notes:
                for sub in str(line).splitlines():
                    s.log.say(f"      {sub}")
            s.log.say("")
    for n in wanted:
        c = s.results.get(n)
        if c:
            s.log.write(f"check{n}", "\n".join(c.notes))

    total = hms(now() - started)
    if failed:
        s.log.say(f"{failed} of {len(wanted)} FAILED — the fleet is not sound   ({total})")
    else:
        s.log.say(f"all {len(wanted)} pass — the fleet is sound   ({total})")
    s.log.say(f"full evidence: {s.dir / 'run.log'}")
    if args.keep:
        s.log.say("--keep: clones, agents and workspaces were LEFT RUNNING. "
                  f"Close them with `sb cleanup --force` inside {s.dir}/*.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
