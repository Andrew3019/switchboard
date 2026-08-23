"""The `sb` command — the only surface agents ever see.

Six verbs for agents (`delegate`, `tell`, `inbox`, `done`, `block`, `status`), a
few more for the human (`init`, `doctor`, `cleanup`, `restore`, `inspect`,
`log`, `presets`, `models`, `workspace`), and `plugin`, which is a namespace rather
than a verb: `sb plugin <name> <verb>` is whatever a plugin declared, and `sb plugin list`
says what this repo has.

Every command takes `--json`, on either side of the subcommand, so wrapping this in an MCP
server later is mechanical (C13). It was global-only for a while, which cost a QA run its
first three spawn attempts; `tests/test_status.py` now builds the check from the parser's
own subcommand list so a verb added later cannot quietly miss it.

Arguments are checked here and nowhere else (see `_validate` and validate.py). This is
the last point where an error can name the flag the caller typed: below it, a bad value
comes back as a herdr error code, far from the caller that caused it.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Any, NamedTuple, Optional

from . import config
from . import guidance
from . import models as models_mod
from . import panel as panel_mod
from . import plugins as plugins_mod
from . import presets as presets_mod
from . import roles as roles_mod
from . import status as status_mod
from . import store
from . import validate
from . import broker as broker_mod
from .broker import HUMAN, Broker
from .herdr import Herdr, HerdrError


def _emit(args, human: str, data: Any = None) -> None:
    if getattr(args, "json", False):
        print(json.dumps(data if data is not None else {"ok": True}, default=str))
    elif human:
        print(human)


def _preset_dir_help() -> str:
    """Where preset files live, spelled the way the config says rather than restated here.

    Same reasoning as `_tier_help`: a path written into a help string is a path that lies
    the moment `[paths]` moves it, and help is exactly where someone looks to find out.
    """
    return "{}/{}/".format(config.setting("paths.repo_dir"),
                           config.setting("paths.presets_dir"))


def _tier_help() -> str:
    """The `--model` help line, read off the tier table instead of restated here.

    Tier names are user vocabulary (C12) — the set is open, so a hardcoded list is wrong
    the moment anyone adds a tier, and it silently advertises tiers a repo may have
    renamed. Generated instead, from exactly the table `delegate` will resolve against.

    Everything is caught: this runs while the parser is being BUILT, before we know we are
    in a repo at all, and `sb --help` outside one — or with a typo in models.toml — must
    still print help rather than a traceback. The shipped names are a fine fallback,
    because they are what an unreadable config layer falls back to anyway.
    """
    try:
        names = models_mod.load(store.worktree_root()).names()
    except Exception:
        names = sorted(models_mod.SHIPPED["tiers"])
    return f"{' | '.join(names)}, or a model id (see: sb models)"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sb", description="switchboard")
    p.add_argument("--json", action="store_true", help="machine-readable output")

    # `sb <cmd> --json` is what anyone actually types — `sb --json <cmd>` requires knowing
    # that argparse cares which side of the subcommand a global flag sits, which nobody
    # does until it has cost them three attempts. Both work, via a parent parser every
    # subcommand inherits.
    #
    # SUPPRESS is load-bearing: it makes the per-command flag only ever *set* the value.
    # A plain store_true would default to False on the subparser and silently undo
    # `sb --json <cmd>`.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="machine-readable output")

    sub = p.add_subparsers(dest="cmd", required=True)

    # Names shown in `--help`. A hidden command is still perfectly callable — this
    # only governs what the help text advertises.
    visible: list[str] = []

    def cmd(name: str, *, hidden: bool = False, **kw) -> argparse.ArgumentParser:
        if not hidden:
            visible.append(name)
        return sub.add_parser(name, parents=[common], **kw)

    st = cmd("start", help="start a top-level dispatcher in a workspace of its own")
    st.add_argument("task", nargs="?", help="optional first instruction")
    st.add_argument("--name", help="name it — and, if an orchestrator of that name is "
                                   "running, hand the task to that one instead of "
                                   "starting another")
    st.add_argument("--model", help=_tier_help())

    # Hidden on purpose. The board is a human's screen, and `sb` is the vocabulary
    # agents are handed — see the refusal in main(). SUPPRESS keeps it out of
    # `sb --help`, and it is absent from defaults/protocol.md, which is where an
    # agent actually learns what `sb` can do. `python3 -m switchboard.board` stays
    # the equivalent, unhidden way in.
    cmd("board", hidden=True)

    # Hidden for the same reason: it is machinery, not vocabulary. Every `sb` command
    # already flushes the doorbell before it dispatches (see main), so this one is that
    # and nothing else — the verb the collector's loop runs so that a message held back
    # while its target was mid-turn is announced without waiting for a person to type
    # something. An agent has no use for it and is not taught it.
    cmd("flush", hidden=True)

    # Hidden for the same reason, and the same shape: the verb the collector's loop runs so
    # that an agent whose turn ended without `sb done` or `sb block` is told so. The
    # decision lives in `Broker.reconcile`, running here in a short-lived process on current
    # code, because the loop that triggers it is version-stale by design (collector module
    # note). An agent has no use for it and is not taught it.
    cmd("reconcile", hidden=True)

    d = cmd("delegate", help="spawn a child agent to do a task")
    d.add_argument("task")
    d.add_argument("--role", default=broker_mod.DEFAULT_ROLE)
    d.add_argument("--as", dest="as_prompt", help="ad-hoc role prompt instead of a named role")
    d.add_argument("--with", dest="with_", action="append", default=[], metavar="PRESET",
                   help=f"preset from {_preset_dir_help()}, or @<plugin> for that plugin's "
                        f"fragment (repeatable); an unknown BARE value is used as a literal "
                        f"instruction, but @ is reserved and an unknown @name is an error")
    d.add_argument("--name", metavar="TOPIC",
                   help="two or three words for the subject — the agent is named "
                        "<role>-<topic>, and that is also its workspace and its branch. "
                        "Required: a spawn with nothing to be named for is refused")
    d.add_argument("--workspace", metavar="NAME",
                   help="join this EXISTING workspace instead of working where you are "
                        "(a workspace is opened by a dispatcher delegating: the "
                        "child's --name is the workspace's name)")
    # WHERE the child works, when nothing else has already decided (`--workspace` and a
    # top's fork both outrank it — broker `isolates`). `own` needs the `fork` capability.
    d.add_argument("--isolation", choices=broker_mod.ISOLATIONS,
                   default=broker_mod.ISOLATION_SHARED,
                   help="'shared' (default) works in YOUR checkout, alongside you and "
                        "your other children; 'own' gives this child a worktree and "
                        "branch of its own to be merged back later (needs `fork`)")
    d.add_argument("--model", help=_tier_help())

    # A capability, handed to an agent in your own subtree, for the rest of its life.
    # There is deliberately NO `sb revoke` and no `--ttl`: the agent's lifecycle is the
    # grant's, `cleanup` ends it and `restore` starts a fresh one from the stored seed. A
    # revoke would be a second, racier way to say `cleanup`, and a TTL would put a clock on
    # a decision nobody would be watching when it fired.
    g = cmd(
        "grant", help="give an agent below you a capability it does not have",
        description="One-shot and permanent for that agent's life: it holds the capability "
                    "until it closes, and there is no revoke. You may grant only what you "
                    "hold yourself, and only inside your own subtree — a grant hands a "
                    "right to somebody another lead is answerable for, so cross-subtree "
                    "sharing goes through the agent you both report to. A grant never "
                    "targets you: rights are somebody else's to give.")
    g.add_argument("agent", help="who gets it — must be in your subtree, and not you")
    g.add_argument("cap", metavar="CAPABILITY",
                   help="the capability string (see the refusal for the list)")
    # The pass-through half of the model, and the flag exists because "may do it" and "may
    # hand it down" are two different decisions: a read-only researcher equips the workers
    # it spawns without ever becoming a writer itself.
    g.add_argument("--delegable", action="store_true",
                   help="the agent may pass this DOWN to what it spawns, without being "
                        "able to do it itself")
    g.add_argument("--reason", help="why, recorded with your name against the grant")

    # The other half of `--isolation own`: a fork gives a child its own branch, and this
    # is the way back off it. Assembly, not landing — see `Broker.merge`.
    mg = cmd(
        "merge", help="fold a finished child's branch into YOUR branch",
        description="One child at a time, into the branch you are already on, in your own "
                    "checkout. Call it as each isolated child finishes: the fourth merges "
                    "against the result of the first three. It never pushes, never touches "
                    "main and opens no pull request — landing the assembled branch is the "
                    "separate step that already exists. It refuses on a dirty checkout and "
                    "names what is uncommitted rather than stashing, because your other "
                    "children share that checkout. A real conflict spawns ONE integrator "
                    "to resolve that merge, and you carry on with the next child once it "
                    "is done.")
    mg.add_argument("child", help="the finished child whose branch is folded in")

    # The reverse of a grant: per-row rendering says what ONE agent may do, and this says
    # who may do one THING. Not human-only and not subtree-scoped — an audit that stops at
    # the caller's own subtree cannot answer the question anybody asks it (§2.1).
    wh = cmd("who-holds", help="list every agent holding a capability, project-wide",
             description="The reverse capability query. One scan over the capability "
                         "rows, so it does not depend on the tree's shape and a promote "
                         "cannot invalidate it. Says who may DO the thing and, apart, who "
                         "may only pass it DOWN — and who granted it.")
    wh.add_argument("cap", metavar="CAPABILITY", help="the capability string")

    t = cmd("tell", help="send a message, do not wait")
    t.add_argument("who", nargs="+")
    t.add_argument("message")
    # Says what it does to the RECIPIENT, because what it does to the sender is nothing:
    # `tell` still returns immediately, and no agent ever waits on another agent.
    t.add_argument("--needs-reply", action="store_true",
                   help="tell them you are waiting for a reply — they are asked to answer "
                        "at some point. You do not wait: this returns immediately")
    # DESIGN-TRUTH: "`sb tell` has three delivery modes." Mutually exclusive because they
    # are one choice with three answers, and argparse saying so beats the broker raising on
    # a combination that was never meant to exist. No `--next-turn` flag: the default is
    # the answer for almost every message, and a flag for it would only invite the reader
    # to think there is a fourth thing to decide.
    m = t.add_mutually_exclusive_group()
    m.add_argument("--when-idle", dest="mode", action="store_const",
                   const=broker_mod.WHEN_IDLE,
                   help="hold it until they have finished what they are doing. The "
                        "default reaches them at their next step, which is sooner")
    m.add_argument("--interrupt", dest="mode", action="store_const",
                   const=broker_mod.INTERRUPT,
                   help="CANCEL what they are doing and deliver this instead — for "
                        "changing course, not for being quick")
    t.set_defaults(mode=broker_mod.NEXT_TURN)

    # Agents only. A human has no mailbox — see the `inbox` branch in `run`.
    ib = cmd("inbox", help="read your unread messages")
    ib.add_argument("--peek", action="store_true",
                    help="do not mark as read (safe for polling)")

    dn = cmd("done", help="you have finished")
    dn.add_argument("summary")

    bl = cmd(
        "block", help="stop and surface to the human (they answer with `sb tell`)",
        # Says the gate exists before a caller trips it. The rule is the protocol's — one
        # agent waits on a person for one question — and `broker.block` is what enforces
        # it; this only keeps the refusal from being a surprise, like the `why` note below.
        description="Refused while somebody below you is already waiting on a person: that "
                    "row is theirs, and the report to make instead is `sb done` naming who "
                    "is waiting and what for.")
    # The help string is where a caller looks before its first block, so it states the
    # split rather than just naming the field: the full text goes in the chat, one line
    # comes here. Enforced in validate.reason — this only stops the enforcement being a
    # surprise.
    bl.add_argument("why", help="ONE short line for the board; write the full question in "
                                "your own chat, which is what the human reads")

    ss = cmd("status", help="the agent tree, with drift and what needs you")
    # `--live` is the older spelling of the same want and stays forever: it is in scripts,
    # and in muscle memory. One dest, so they can never disagree.
    ss.add_argument("--active", "--live", dest="live", action="store_true",
                    help="hide finished agents")
    ss.add_argument("--needs-me", dest="needs_me", action="store_true",
                    help="only agents that are blocked, at a prompt, stalled, or holding "
                         "unread mail")
    # A human has no subtree — `_subtree` reads `human` as every root and everything under
    # it, so the flag filters nothing for them. Says that rather than "for a human: every
    # agent", which read as an invitation to use this as their view; theirs is `sb board`.
    ss.add_argument("--mine", action="store_true",
                    help="only your own subtree (a human has no subtree: every agent is "
                         "theirs, and `sb board` is their view of them)")
    # Not a filter, unlike the three above: they drop rows and say so in `hidden`, this
    # only stops fully-archived subtrees being drawn as one line each. `--json` is
    # unaffected either way and always carries every row.
    ss.add_argument("--archived", action="store_true",
                    help="draw archived agents individually instead of collapsing them "
                         "(the default is display.show_archived)")
    # Naming one prints it. A preset is not always a disposition stapled onto a spawn —
    # some are procedures an agent is TOLD to go and follow, and without a way to read one
    # on demand the only way to reach a procedure was to be spawned with it already
    # attached, paying its length on every such spawn forever. Read-only, load level 1, no
    # plugin import: safe for an agent to run mid-turn.
    pr = cmd("presets", help="list available presets, print one, or apply one to yourself")
    pr.add_argument("name", nargs="?", help="print this preset instead of listing")
    # The third parameter asked for, next to list and read —
    # DESIGN-TRUTH: "`sb presets` needs a parameter to list, and one to apply the prompt"
    # — and applying pastes it into the caller's OWN session, the same path as any message,
    # so it arrives tagged and durable rather than as command output. No confirmation step
    # and no dry run — an agent that types this has already decided.
    pr.add_argument("--apply", action="store_true",
                    help="paste this preset into your own session instead of printing it")
    # REMAINDER, so the top-level parser stays static and unbreakable by anything on
    # disk. Registering plugin commands here would mean importing plugin code to print
    # `sb --help` — and `_tier_help` above already has to wrap a config read in a bare
    # `except Exception` so that `sb --help` outside a repo does not traceback. One such
    # hazard is enough. The plugin's own arguments are parsed after dispatch, by the
    # subparser sb builds from what `register()` declared, so deferring costs nothing in
    # error quality: `sb plugin todo add --labl x` still names the flag that was typed.
    pl = cmd("plugin", help="run an installed plugin (see: sb plugin list)")
    pl.add_argument("name", nargs="?", help="plugin name, or `list`")
    pl.add_argument("rest", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    # Retired, and loud about it rather than silently gone: `sb plugins` used to be this
    # verb, and the word now belongs to code plugins instead. Hidden, because a retired
    # spelling should not be advertised, but still REGISTERED — an unregistered verb gets
    # an argparse usage dump, which names neither replacement. See `_dispatch`.
    cmd("plugins", hidden=True)
    # The sibling of `presets`: both answer "what vocabulary does THIS repo have?", which
    # is the question you have right before typing `--model` or `--with`. Read-only, and
    # the only place a resolved model name is ever printed — a tier is opaque by design,
    # so without this the only way to learn what one maps to is to read three config files.
    cmd("models", help="show the resolved model tiers for this repo")
    cmd("init", help="pin this repo for switchboard (writes no CLAUDE.md)")
    doc = cmd("doctor", help="check herdr, version, and integration conflicts")
    # The way out of the one deadlock the store can get into: a schema change that is not
    # additive cannot be applied while agents are live, and `connect()` is the first thing
    # EVERY command does — including the `sb done` an agent would need to run to stop being
    # live. `store._reset`'s own error names this flag, so it has to exist.
    doc.add_argument("--reset-store", action="store_true",
                     help="drop and recreate the store (operational state only)")
    doc.add_argument("--force", action="store_true",
                     help="with --reset-store: do it even though agents are running")

    c = cmd(
        "cleanup", help="close finished agents, ones switchboard gave up on, and the "
                        "spaces they leave empty",
        description="With no name, closes every finished agent in your subtree (for a "
                    "human: all of them), plus any whose turn switchboard itself gave up "
                    "on — a crashed session nobody reported an end for, as long as "
                    "sb restore can still bring it back. Naming agents "
                    "closes those instead, at the same bar; --force is what closes one "
                    "whatever state it is in, and everything still open under it. "
                    "A space whose agents have all finished is "
                    "then closed too — its worktree deleted, on the same gates as "
                    "`sb workspace close`, which keep anything dirty or still busy. "
                    "Never the space you are standing in.")
    c.add_argument("name", nargs="*", help="specific agents to close")
    c.add_argument("--force", action="store_true",
                   help="close a NAMED agent whatever state it is in, unread mail and all, "
                        "and its whole subtree with it, leaves first (the escape hatch for "
                        "one that is genuinely stuck)")
    c.add_argument("--dry-run", action="store_true")

    # Hidden for `board`'s reason: it is a human's housekeeping, not an agent's
    # vocabulary, and it is refused for an agent caller in `_dispatch` rather than merely
    # hidden. A board runs it twice an hour on its own (`switchboard/sweep.py`); this is
    # the same run, typed, and it is how a person sees what the automatic one would do.
    sw = cmd("sweep", hidden=True,
             description="Delete every worktree with nothing left to lose: no live agent, "
                         "nothing git can see uncommitted, its commits merged or pushed "
                         "(or docs-only), and quiet for over a day on both clocks. Every "
                         "deletion is `sb workspace close`'s, gates and all.")
    sw.add_argument("--dry-run", action="store_true",
                    help="say what would go and what holds each of the rest, delete nothing")

    # No `new` here. A space is minted by ONE path — a top's `sb delegate` — and this verb
    # is what is left of workspaces once that is true: the two read/teardown halves, which
    # are the human's, not an agent's. See DESIGN-TRUTH.md's "`sb workspace new` is
    # deleted, provided the other commands cover it fully".
    w = cmd("workspace", help="workspaces (worktree + herdr workspace + lead)")
    wsub = w.add_subparsers(dest="wcmd", required=True)

    wsub.add_parser(
        "list", parents=[common],
        help="every workspace: where it is, what is live in it, what is left behind",
        description="The cross-reference that otherwise has to be done by hand. Built "
                    "from the union of `git worktree list`, the workspaces table and the "
                    "agent rows, because each one knows something the other two cannot — "
                    "an orphan checkout with no rows, a retired workspace with no "
                    "checkout, a workspace that escaped the table.")
    wc = wsub.add_parser(
        "close", parents=[common],
        help="retire a workspace, and remove its checkout if it still has one",
        description="Checks what is still in the checkout — our own rows AND every "
                    "process actually sitting in the directory — closes the workspace's "
                    "panes, checks again, then deregisters the one named worktree (never "
                    "a repo-global prune) and deletes its branch with the safe delete "
                    "that refuses an unmerged one. A workspace with no checkout of its "
                    "own is simply retired: there is nothing there to lose.")
    wc.add_argument("name")
    wc.add_argument("--yes", dest="confirm", action="store_true",
                    help="delete the ignored files the refusal listed along with the "
                         "checkout (git does not track them and will not miss them)")
    wc.add_argument("--resume", action="store_true",
                    help="take over a retiring mark left behind by a teardown that died, "
                         "and run the whole command again — never for an owner confirmed "
                         "still going")

    r = cmd(
        "restore", help="bring a closed agent back with its context",
        description="Names one agent and brings it back in a fresh pane, resumed, in the "
                    "workspace it came from. --sweep instead brings back everything that "
                    "went down in the last few minutes and has not been dealt with — the "
                    "one command for after a herdr restart. What --sweep can reach is "
                    "your own scope, and that is the whole point to know about it: run by "
                    "a HUMAN it covers every tree in the store, which is the only way it "
                    "means 'everything'; run by an agent it covers that agent's own "
                    "subtree and nothing else, so a crash spread across several trees "
                    "needs the human to type it. Agents with no recorded session id "
                    "cannot be restored at all; they are named in the report rather than "
                    "left out of it.")
    r.add_argument("name", nargs="?", help="the agent to bring back")
    r.add_argument("--sweep", action="store_true",
                   help="bring back everything in your scope that recently went down, "
                        "parents before children (a second run is a no-op)")
    r.add_argument("--dry-run", action="store_true",
                   help="with --sweep: classify the cohort and print it, restore nothing")

    ins = cmd(
        "inspect", help="everything about ONE agent, including its recent terminal output",
        description="What is going on with this agent: its task, state, drift, workspace, "
                    "mail, last summary, recent "
                    "events, and the tail of its terminal — live pane if it has one, the "
                    "on-disk transcript if it does not.")
    ins.add_argument("name")
    ins.add_argument("-n", type=int, default=status_mod.DEFAULT_LINES,
                     help="lines of terminal output to show")
    ins.add_argument("--events", type=int, default=status_mod.DEFAULT_EVENTS,
                     help="how many recent events to include")

    lg = cmd("log", help="recent events (debugging)")
    lg.add_argument("--agent")
    lg.add_argument("-n", type=int, default=config.setting("display.log_events"))

    # argparse builds this from every registered choice, hidden ones included, and
    # `add_parser(help=SUPPRESS)` does not suppress a subcommand — it prints a
    # literal "==SUPPRESS==" instead. So the list is rewritten from `visible`.
    sub.metavar = "{" + ",".join(visible) + "}"
    return p


def _validate(args) -> None:
    """Check and normalise every argument, before anything spawns or is written.

    All of it happens here, at the boundary, rather than in the broker: once a value has
    reached the broker it is already on its way into herdr or the store, and herdr's own
    complaint about it names neither the flag that carried it nor the fix. Validators
    return the normalised value, so this writes back onto the namespace — downstream code
    then sees the stripped, checked version and nothing else has to care.

    See validate.py for the rules; the two that bite are herdr's agent-name pattern and
    its outright refusal of a newline in ANY agent argument.
    """
    cmd = args.cmd

    if cmd == "start":
        if args.name is not None:
            args.name = validate.agent_name(args.name, "--name")
        if args.task is not None:
            args.task = validate.line(args.task, "task")
        # Same rule as `delegate --model`, and deliberately the same call: both take a
        # TIER name out of the same open vocabulary, so a value one accepts and the other
        # rejects would be two answers to one question.
        if args.model is not None:
            args.model = validate.token(args.model, "--model")

    elif cmd == "delegate":
        args.task = validate.line(args.task, "task")
        # Not slugified here: the role is also a lookup key into roles.toml, and a role
        # nobody defined is legal (roles.get falls back to worker). Only the composed agent
        # name has to satisfy herdr, and `Broker._compose_name` slugs it there.
        args.role = validate.line(args.role, "--role", max_len=validate.MAX_TOKEN)
        # NOT `agent_name`: `--name` is no longer the name. It is the topic half, and the
        # broker composes `<role>-<topic>` from it (`Broker._compose_name`), so a topic
        # checked against herdr's 32 characters here would pass and then compose into
        # something too long. Checked as a LINE, and slugged by the broker with the role in
        # front so the truncation falls on the topic rather than on the prefix.
        if args.name is not None:
            args.name = validate.line(args.name, "--name", max_len=validate.MAX_TOKEN)
        # A workspace name IS a branch name, so it is checked as one — the same rule
        # `sb workspace close` is held to, since both name the same place.
        if args.workspace is not None:
            args.workspace = validate.ref_name(args.workspace, "--workspace")
        if args.model is not None:
            args.model = validate.token(args.model, "--model")
        if args.as_prompt is not None:
            args.as_prompt = validate.line(args.as_prompt, "--as",
                                           max_len=validate.MAX_PROMPT)
        # A `--with` value is either a preset name or a literal instruction; both become
        # prompt text, so both are checked again after resolution (see _dispatch).
        args.with_ = [validate.line(w, "--with", max_len=validate.MAX_PROMPT)
                      for w in args.with_]

    elif cmd == "grant":
        args.agent = validate.agent_name(args.agent)
        # One word, and the broker checks it against the vocabulary — this only keeps a
        # sentence out of the column. Names like `write-tracked` carry a hyphen, which
        # `token` allows; whitespace is what it refuses.
        args.cap = validate.token(args.cap, "capability")
        if args.reason is not None:
            args.reason = validate.line(args.reason, "--reason")

    elif cmd == "merge":
        args.child = validate.agent_name(args.child)

    elif cmd == "who-holds":
        args.cap = validate.token(args.cap, "capability")

    elif cmd == "tell":
        args.who = validate.targets(args.who)
        # An interrupt's text travels INLINE — it is the prompt herdr sends, and herdr
        # refuses any agent argument holding a newline. The other two modes only ring a
        # fixed doorbell, so their body never reaches that call and may be as long and as
        # multi-line as the sender likes. Checked here rather than left to herdr, which
        # would fail after the escape keypress had already cancelled the target's turn.
        if args.mode == broker_mod.INTERRUPT:
            args.message = validate.line(args.message, "message")
        else:
            args.message = validate.text(args.message, "message")

    elif cmd == "done":
        # herdr carries the summary as `report-agent --message`, so one line.
        args.summary = validate.line(args.summary, "summary")

    elif cmd == "block":
        # Not `line`: the reason has its own rule and its own error, because the human
        # never reads this field and a caller told only "one line" flattens a report into
        # it. See validate.reason.
        args.why = validate.reason(args.why)

    elif cmd == "workspace":
        # `list` takes no arguments at all and `close` takes only a name, so each one is
        # checked for what it actually carries.
        if getattr(args, "name", None) is not None:
            args.name = validate.ref_name(args.name)

    elif cmd == "restore":
        # One shape or the other, never both and never neither. A bare `sb restore` used
        # to be an argparse usage error and still has to say something, and `sb restore
        # <name> --sweep` is two different commands typed at once — guessing which one was
        # meant would spawn panes nobody asked for.
        if args.sweep and args.name is not None:
            raise validate.Invalid(
                "`sb restore --sweep` takes no name: it is the whole recent cohort. "
                f"For one agent: `sb restore {args.name}`")
        if not args.sweep:
            if args.name is None:
                raise validate.Invalid(
                    "`sb restore` needs the name of the agent to bring back — or "
                    "`sb restore --sweep` for everything that recently went down")
            args.name = validate.agent_name(args.name)
        if args.dry_run and not args.sweep:
            raise validate.Invalid("--dry-run belongs to `sb restore --sweep`")

    elif cmd == "inspect":
        args.name = validate.agent_name(args.name)
        args.n = validate.positive_int(args.n, "-n")
        args.events = validate.positive_int(args.events, "--events")

    elif cmd == "cleanup":
        args.name = [validate.agent_name(n) for n in args.name]

    elif cmd == "log":
        if args.agent is not None:
            args.agent = validate.agent_name(args.agent, "--agent")
        args.n = validate.positive_int(args.n, "-n")

    elif cmd == "plugin":
        _validate_plugin(args)


def _plugins_file() -> str:
    """Where enablement is written, spelled the way the config says. See `_preset_dir_help`."""
    return "{}/{}".format(config.setting("paths.repo_dir"),
                          config.setting("paths.plugins_file"))


def _validate_plugin(args) -> None:
    """Resolve the plugin, its command, and its arguments — here, like everything else.

    This is level 3 and level 3 only happens for `sb plugin …`: the name is looked up, the
    module is imported, `register()` is called, and the rest of the command line is parsed
    by the subparser sb builds from what it declared. Doing it in `_validate` rather than in
    `_dispatch` keeps cli.py's one rule intact — arguments are checked at the boundary and
    nowhere else — and means a typo is answered before the store is even opened.

    Everything resolvable is stashed on the namespace, so `_dispatch` looks nothing up
    twice and the import happens exactly once per invocation.
    """
    if args.name is None:
        raise validate.Invalid("`sb plugin` needs a plugin name — see `sb plugin list`")

    if args.name == "list":
        # A verb, not a plugin: `list` and `info` are reserved names. Parsed rather than
        # waved through, so `sb plugin list --oops` is a usage error like any other.
        lp = argparse.ArgumentParser(prog="sb plugin list",
                                     description="what this repo has, and its state")
        lp.add_argument("--json", action="store_true", help="machine-readable output")
        args.json = lp.parse_args(args.rest).json or args.json
        return

    try:
        repo = store.worktree_root()
    except Exception:
        # Not in a repo. `store.connect()` is a few lines below and says so far better than
        # a complaint about a plugin name could.
        return

    found = plugins_mod.available(repo)
    if args.name not in found:
        raise validate.Invalid(
            f"no such plugin: '{args.name}'{plugins_mod.did_you_mean(args.name, found)}"
            f" — see `sb plugin list`")
    if args.name not in plugins_mod.enabled(repo):
        raise validate.Invalid(
            f"plugin '{args.name}' is not enabled — add it to "
            f"{_plugins_file()}: enabled = [\"{args.name}\"]")

    p = plugins_mod.must_load(repo, args.name)          # PluginError -> caught in main
    if args.rest and not args.rest[0].startswith("-") and args.rest[0] not in p.commands:
        raise validate.Invalid(
            f"plugin '{p.name}' has no command '{args.rest[0]}'"
            f"{plugins_mod.did_you_mean(args.rest[0], p.commands)} — "
            f"try: {', '.join(sorted(p.commands))}")

    # argparse from here: `--help`, a missing command, an unknown flag and a bad choice all
    # come back in sb's own voice and exit 2, because they ARE sb's parser.
    ns = plugins_mod.build_parser(p).parse_args(args.rest)
    args.plugin = p
    args.command = p.commands[ns._command]
    args.pargs = ns
    args.json = getattr(ns, "json", False) or args.json


# The only verbs refused while the store is degraded — see `store.schema_deficit`. All
# three create an agent, which is what writes the columns a degraded store does not have;
# everything else runs, because a live fleet has to be able to drain itself and a human has
# to be able to watch it do so. A deny-list, not an allow-list, on purpose: a verb added
# later defaults to *working*, and after a deadlock that cost seventeen agents, that is the
# direction to be wrong in.
#
# `workspace` left the list with `workspace new`: what is left of the verb reads and tears
# down, and a store too old to spawn into is exactly when a human still needs both.
_NEEDS_FRESH_SCHEMA = {"start", "delegate", "restore"}


# Markers that say the typing is not being done by a human, any one of which is enough.
# The first two are Claude Code's, set in the environment of every command such a session
# runs — two rather than one because different parts of that harness set them and an agent
# with only one of them is still an agent. The third is switchboard's own, put on the pane
# at creation (`Broker._spawn_env`) and inherited by everything the agent runs; it is the
# only one a codex agent has, since codex sets no session variable of its own.
_AGENT_SESSION_ENV = ("CLAUDE_CODE_SESSION_ID", "CLAUDECODE", "SB_AGENT")


def _agent_caller(me: str) -> Optional[str]:
    """The agent behind this call, described; None if a human is typing.

    Two signals, because one of them has a hole exactly where it matters.

    `whoami()` is the good signal: it resolves a caller against the agents THIS store
    knows, by session id, agent name or pane id, all three injected into every pane we
    spawn. It is what
    `sb board` is gated on. But it can only recognise an agent the store has a row for,
    and an agent standing in a fresh `git clone` is driving that clone's own store, which
    has no rows at all — so it resolves to HUMAN. That clone is not a hypothetical: it is
    this repo's verification convention, and it is how an agent created three unwanted top
    agents in one afternoon.

    So the environment is the second signal, and it is the one that closes the clone: an
    agent's pane carries a marker in the environment of every command it runs, wherever it
    is standing and whatever store it is talking to.

    This fails CLOSED on the unnameable caller, and the cost is worth naming: a human who
    runs `sb start` from inside an agent session — `!sb start` at the prompt — is
    refused along with the agents, because at that point nothing distinguishes them.
    Failing open instead would leave the rule enforced only where it was already enforced.
    A human's own terminal carries neither marker and is untouched, which is the case the
    command exists for.
    """
    if me != HUMAN:
        return f"you are '{me}'"
    if any(os.environ.get(v) for v in _AGENT_SESSION_ENV):
        # No name to give: an agent this store has never heard of, which in practice means
        # one running against a clone's store rather than the fleet's.
        return "you are an agent, and this store has no row for you"
    return None


def _scope(b: Broker, me: str, mine: bool) -> dict:
    """What `sb status` is allowed to show this caller, as `collect`'s two scope kwargs.

    `tree` is the boundary — the caller's own top's whole tree, siblings included, or
    `None` for the human, who is bounded by nothing —
    DESIGN-TRUTH: "Only agents have the scope constraints."
    `mine` is the `--mine` flag and still means the caller's own subtree, which is
    narrower; the flag asks for less and cannot ask for more.

    Before this, both were off by default, which is why any agent could read every other
    tree's state by typing the command with no flags at all.
    """
    return {"tree": b.tree_of(me), "mine": me if mine else None}


def _who_holds_text(cap: str, holders: list) -> str:
    """`sb who-holds` as lines. Held first, pass-through after, and never mixed.

    The order is the answer to the question, not a preference: somebody asking who can
    `write-tracked` is asking who can write, and a list that interleaved the agents that
    may only hand it down would read as a longer list of writers. Provenance sits on the
    line because it is what the divergence marker deliberately does NOT carry (§2.5) —
    the column says a row diverged, this says who did it and why.
    """
    if not holders:
        return f"nobody holds {cap}"
    lines = []
    for kind, word in (("held", "holds"), ("delegable", "may pass down")):
        rows = [h for h in holders
                if (h["held"] if kind == "held" else not h["held"] and h["delegable"])]
        if not rows:
            continue
        lines.append(f"{word} {cap}:")
        for h in rows:
            how = ("from its role (a row older than the capability table)" if h["derived"]
                   else f"granted by {h['granted_by']}" if h["granted_by"]
                   else "seeded at spawn")
            why = f" — {h['reason']}" if h["reason"] else ""
            lines.append(f"  {h['agent']}  ({h['role']}, {h['state']})  {how}{why}")
    return "\n".join(lines)


# THE COMMANDS WHOSE OUTPUT CARRIES THE CALLER'S STATE (E2, spec §2.4), and the key a
# `command` guidance rule is matched on. Deliberately short, and chosen by a rule rather
# than by taste: these are the verbs that SPEND something of the caller's — a capability
# (`delegate` spends `spawn` and `fork`, `grant` spends what you hold or may pass down),
# or a resource it is answerable for (`merge` folds another branch into your checkout,
# `workspace close` destroys one). They are exactly the commands where "what am I, and
# where am I?" changes what the caller should do next.
#
# Everything else stays quiet, and that is the half worth defending (obj. 5). `tell`,
# `inbox`, `done`, `block`, `status`, `log`, `inspect` are the verbs an agent runs dozens
# of times a turn-cycle; a state readout under each of them would be the nag-fatigue
# §5 warns about, arriving through a second channel. The read verbs are also the ones
# that already SHOW state — `sb status` draws the divergence marker, `sb who-holds`
# answers about capabilities outright — so a footer there would be a second, shorter
# answer to the question the command was asked.
STATE_COMMANDS = frozenset({"delegate", "grant", "merge", "workspace"})


def _state_key(args) -> Optional[str]:
    """The command key for this invocation, or None on a trivial one.

    `workspace` is the one verb that splits: `close` retires a checkout somebody is
    responsible for, `list` is a read like any other, so the key is the verb only when the
    subcommand is the one that acts.
    """
    cmd = getattr(args, "cmd", None)
    if cmd not in STATE_COMMANDS:
        return None
    if cmd == "workspace" and getattr(args, "wcmd", None) != "close":
        return None
    return cmd


def _state_output(args, b: Broker, db, key: Optional[str]) -> None:
    """Print the caller's own state under a non-trivial command's output, and ask the
    ledger whether any `command`-keyed rule fires (E2, spec §2.4).

    TWO THINGS THROUGH ONE DOOR, and neither is a new mechanism. The readout is
    `guidance.state_note` — what this agent may do, where it is attached, what config it
    runs under, what was granted to it since it was spawned. The rules are
    `guidance.deliver` with the command in hand, which is the call site E1 built the
    `command` key for and left with nobody to call it: until this line existed, a rule
    keyed on a command could never match, because the only resolver call passed None.
    `delegate-to-a-lead` is that rule, and this is where it starts firing.

    A COMPLEMENT TO THE TURN-START CHANNEL, NOT A REPLACEMENT (obj. 2). Both ship, and they
    answer different questions: the hook says "before your next action, remember X" at the
    turn, this says "here is what you are" at the action. The cursor is shared, so a `once`
    rule said here is not said again at the next turn start — one ledger, one memory, two
    moments.

    QUIET IN `--json`. The footer is prose for a reader, and stdout in `--json` mode is one
    JSON document that a program parses; appending lines to it would corrupt the one output
    of `sb` that is machine-readable. A caller that wants this data structured already has
    `sb inspect --json` and `sb who-holds --json`.

    QUIET FOR THE HUMAN, and for a caller with no row: neither holds capabilities, neither
    is attached to anything, and `held_for` answers None for both — the same rowless
    fail-open the capability gate has.

    NEVER FATAL. Wrapped whole, for `hooks.run_activity`'s reason: the command has already
    run and its result is already printed, so a ledger that will not parse or a store that
    lacks the cursor table must cost a reminder nobody got, not an exit code on work that
    succeeded.
    """
    if key is None or getattr(args, "json", False):
        return
    try:
        me = b.whoami()
        if me == HUMAN:
            return
        held, passable = b.held_for(me), b.passable_for(me)
        if held is None or passable is None:
            return
        row = store.get_agent(db, me)
        # The config in effect: the tier this agent was pinned to, else its role's own.
        # `agents.tier` is NULL for every agent nobody pinned, which is most of them, and
        # the role's answer is the true one there.
        tier = (store._value(row, "tier") if row is not None else None) or (
            roles_mod.get(b.roles, row["role"], b.repo).model if row is not None else None)
        text = "\n".join(t for t in (
            guidance.state_note(db, me, held=held, delegable=passable - held, tier=tier),
            guidance.deliver(db, me, command=key, repo=b.repo),
        ) if t)
        if text:
            print(text)
    except Exception:                            # noqa: BLE001 — never over a reminder
        pass


def _degraded(deficit: list[str], cmd: str) -> str:
    """Why this one command cannot run while the rest of `sb` still can.

    Names what is missing, what an agent can still do, and that it clears itself. The old
    message said only "let them finish", which was advice an agent could not take: to
    finish it had to run `sb done`, and `sb done` was the command being refused.
    """
    return (f"sb: `sb {cmd}` cannot run against this store yet —\n"
            + "".join(f"      {d}\n" for d in deficit)
            + "    A fleet is still running on the older store, so it has not been\n"
              "    rebuilt yet. Reporting is unaffected: sb done, sb block, sb tell and\n"
              "    sb inbox all still work, and the store rebuilds itself as soon as the\n"
              "    last agent finishes. To rebuild NOW and lose their state:\n"
              "      sb doctor --reset-store --force")


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        _validate(args)
    except validate.Invalid as e:
        # 2, like argparse's own usage errors: nothing ran, and nothing is wrong with the
        # system — only with what was typed.
        print(f"sb: {e}", file=sys.stderr)
        return 2
    except plugins_mod.PluginError as e:
        # A plugin that will not import. 1, not 2: what was typed was fine.
        return _plugin_failed(e)

    # Before the store, because a retired verb has no work to do and should say so wherever
    # it is typed — including outside a repo, where connect() would answer with something
    # else entirely. Exit 2, like a usage error: nothing ran, and nothing is wrong with the
    # system, only with what was typed.
    if args.cmd == "plugins":
        print("sb: `sb plugins` has been split. Prompt fragments are now `sb presets`;\n"
              "    code plugins are `sb plugin list`.", file=sys.stderr)
        return 2

    # Writable, deliberately, even for `sb status` and `sb log`. This is the short-lived
    # process running current code that `store._connect_readonly` says the migration
    # belongs to — make this readonly and nothing reconciles the schema at all. It is also
    # not read-only in fact: `flush_pending` below writes, `whoami` revives, and `collect`
    # reaps. Making the read verbs genuinely read-only is a bigger change than a flag —
    # see `.switchboard/design/status-truth.md` §6(c).
    try:
        db = store.connect()
    except Exception as e:                       # not in a repo, or an unreadable store
        print(f"sb: {e}", file=sys.stderr)
        return 2

    deficit = store.schema_deficit(db)
    if deficit and args.cmd in _NEEDS_FRESH_SCHEMA:
        print(_degraded(deficit, args.cmd), file=sys.stderr)
        return 1

    h = Herdr(on_event=lambda **kw: store.log_event(db, **kw))
    # THIS worktree, not the main checkout. repo_root() is the shared .git,
    # which is deliberately identical from every worktree.
    repo = store.worktree_root()
    b = Broker(db, h, repo=repo)

    # Every `sb` invocation is also a tick of the doorbell. A message to an agent that was
    # mid-turn is held back rather than injected into its turn (see Broker._ring), and
    # something has to ring it once it is free. That was ONLY the next command anyone
    # happened to run, which left a parent whose last child reported mid-turn waiting for
    # traffic that may never come; `sb flush` is the same tick with nothing after it, and
    # the collector's loop runs it on a timer so the fleet no longer depends on a person.
    # Never fatal: a doorbell that cannot ring must not take down `sb status`.
    rung: list[str] = []
    try:
        rung = b.flush_pending()
    except Exception as e:                       # noqa: BLE001 — best effort, always
        store.log_event(db, kind="flush_failed", error=str(e))

    if args.cmd == "flush":
        _emit(args, f"rang {', '.join(rung)}" if rung else "rang nobody", {"rung": rung})
        return 0

    if args.cmd == "reconcile":
        # Never fatal, for `flush`'s reason turned around: this one runs unattended on the
        # collector's timer, so a failure has nobody to read it and must not be a traceback
        # in a spawned process — it is a line in the log the next `sb log` shows.
        #
        # **`reap=True`, and this is the only unattended path that reaps.** `collect`'s
        # writes end a dead agent's turn and ping its parent (`status._record_gone`), and
        # until now `sb status` was the only caller that passed `reap=True` — so how soon a
        # parent learned its child had died depended on somebody happening to look at the
        # board. With the failure now arriving as mail, that latency is the difference
        # between a notification and archaeology.
        #
        # Here rather than in `flush`, which is the other unattended path and the tempting
        # one: `flush_pending` runs at the top of EVERY `sb` command and is free when the
        # mailbox is quiet — it asks herdr nothing at all unless something is pending — so
        # putting a `collect` in it would buy an `agent list` subprocess for every `sb log`,
        # `sb tell` and `sb inbox` in the fleet. `reconcile` already collects a whole
        # snapshot, already runs on the collector's timer, and is already the verb for "this
        # agent's turn ended and nothing told anyone" — a death is that same sentence with a
        # pane missing. It is also short-lived and running current code, which is the
        # condition `collect` documents for reaping at all.
        #
        # Collected here rather than inside `Broker.reconcile` so the write stays visible at
        # the process boundary that licenses it: the method keeps `reap=False` for any
        # caller that is not this one.
        try:
            snap = status_mod.collect(db, h, reap=True, repo=repo)
            pinged = b.reconcile(snap=snap)
        except Exception as e:                   # noqa: BLE001 — best effort, always
            store.log_event(db, kind="reconcile_failed", error=str(e))
            print(f"sb: reconcile: {e}", file=sys.stderr)
            return 1
        _emit(args, f"pinged {', '.join(pinged)}" if pinged else "pinged nobody",
              {"pinged": pinged})
        return 0

    try:
        code = _dispatch(args, b, db, h)
    except HerdrError as e:
        print(f"sb: herdr [{e.code}] {e.message}", file=sys.stderr)
        code = 1
    except sqlite3.OperationalError as e:
        # On a degraded store this is a command that turned out to need the new schema
        # after all — `_NEEDS_FRESH_SCHEMA` is a judgement, and this is what a wrong
        # judgement looks like from the caller's side. Say which, rather than leaking
        # "no such column: agents.branch" to an agent that cannot act on it.
        print(_degraded(deficit, args.cmd) if deficit else f"sb: store: {e}",
              file=sys.stderr)
        code = 1
    except plugins_mod.PluginError as e:
        # Already logged, by the dispatch that raised it — one event per handler
        # invocation, not two for the ones that failed.
        code = _plugin_failed(e)
    except (ValueError, KeyError) as e:
        print(f"sb: {_reason(e)}", file=sys.stderr)
        code = 1

    # AFTER the command, and on the refusals too. State is most worth reading exactly when
    # a command did not do what its caller expected — an agent refused `--isolation own`
    # wants to see that it does not hold `fork` — and reading it afterwards is what makes
    # it true: a spawn that just moved this agent's child into a new workspace, or a grant
    # that just widened somebody, is already reflected.
    _state_output(args, b, db, _state_key(args))
    return code


def _plugin_failed(e: plugins_mod.PluginError) -> int:
    """One line naming the plugin, never a traceback. Exit 1, like every other failure.

    No exit code is reserved for this, and that is a decision rather than an omission: sb
    has no reserved codes at all, and minting one here would add a second machine-readable
    channel beside the one `--json` already is, where a failed handler is `ok: false` with
    a reason. A plugin that wants a code of its own sets `Result.code`.
    """
    print(e.tb if e.tb and os.environ.get("SB_DEBUG") else f"sb: {e}", file=sys.stderr)
    return 1


def _reason(e: Exception) -> str:
    """The message, without the quotes `str(KeyError)` adds.

    `KeyError("no such agent: w1")` stringifies as `"'no such agent: w1'"`, so half the
    errors this CLI prints came out quoted and half did not — for no reason a reader could
    see, since both are the same kind of "you named something that is not there". Same
    error shape for the same class of mistake.
    """
    return str(e.args[0]) if isinstance(e, KeyError) and e.args else str(e)


def _needs_reply(m) -> bool:
    """Whether this message's sender said it is waiting for a reply.

    Tolerant of the column being absent, which is a real state and not a hypothetical: a
    store kept on the old shape because a live fleet was running (`store.schema_deficit`)
    hands back rows without it, and a `sb inbox` that raised there would take an agent's
    whole mailbox down over a flag. No column means no such message was ever sent.
    """
    try:
        return bool(m["needs_reply"])
    except (IndexError, KeyError):
        return False


def _dispatch(args, b: Broker, db, h: Herdr) -> int:
    cmd = args.cmd

    if cmd == "doctor":
        if args.reset_store:
            try:
                store.reset(db, force=args.force)
            except store.LiveAgentsError as e:
                print(f"sb: {e}", file=sys.stderr)
                return 1
            _emit(args, f"store reset: {store.db_path()}", {"reset": True})
            return 0
        # The store's condition is reported here whatever herdr says. A degraded store is
        # invisible by design — every verb an agent uses keeps working — so `doctor` is
        # the one place it has to be legible, or nobody learns the rebuild is pending.
        deficit = store.schema_deficit(db)
        schema = "".join(f"\n       PENDING REBUILD — {d}" for d in deficit)
        if schema:
            schema += ("\n       (a fleet is live; it rebuilds when the last one finishes)")
        # Level 3: `doctor` imports every plugin, which is exactly what it is for. Wrapped
        # per plugin by `load_all`, so the one that will not import is a row here rather
        # than a traceback instead of the report.
        pl = _doctor_plugins(b.repo)
        # Whether the panel every pane is drawing is actually fresh. The counters ride in
        # the snapshot file the collector writes anyway, so this costs no store write —
        # see `panel.doctor_line`, and split-tab.md §2.5 for why it is not an `on_event`.
        panel_line = "\n" + panel_mod.doctor_line()
        try:
            h.check()
            _emit(args, f"herdr {h.version()} ok\nstore  {store.db_path()}{schema}"
                        f"{panel_line}{pl.text}",
                  {"ok": not deficit and not pl.problems, "schema_deficit": deficit,
                   "panel": panel_mod.doctor_dict(), **pl.data})
        except HerdrError as e:
            _emit(args, f"PROBLEM [{e.code}]\n  {e.message}{schema}{pl.text}",
                  {"ok": False, "code": e.code, "schema_deficit": deficit, **pl.data})
            return 1
        # Non-zero for a pending rebuild, so the exit code and the `ok` field cannot
        # disagree. Nothing is broken — but `doctor` is the verb whose whole job is to
        # say so out loud, and a script checking it should see the difference.
        #
        # Plugin PROBLEMS join it; plugin NOTICES do not. An orphaned state directory is
        # permanent by design — nothing ever deletes it and the human may well be keeping
        # it — so letting one hold `sb doctor` at non-zero forever would train everybody to
        # stop reading the exit code, which is the only thing it is for.
        return 1 if (deficit or pl.problems) else 0

    if cmd == "init":
        p = b.init()
        _emit(args, f"switchboard initialised for {p}\n"
                    f"(no CLAUDE.md written — the protocol travels as a system prompt)",
              {"repo": str(p)})
        return 0

    me = b.whoami()

    if cmd == "board":
        # The one verb in `sb` that an agent may not run. Gated on identity rather
        # than on hiding it: hiding stops it being *learned*, this stops it being
        # *used*, and only the second one holds if a agent guesses the name.
        #
        # Fails closed. `whoami()` resolves an agent by session id or pane id, both
        # injected into every pane we spawn, so anything with an agent row is
        # refused; only a caller with no row at all reads as the human.
        if me != broker_mod.HUMAN:
            print(f"sb: board is a human-only view; you are '{me}'.\n"
                  f"    Use `sb status` for the same tree as text.", file=sys.stderr)
            return 1
        from . import board as board_mod
        return board_mod.main()

    if cmd == "start":
        # Only a human creates a top dispatcher (DESIGN-TRUTH, confirmed 2026-08-11).
        # The worktree refusal in `Broker._refuse_outside_main_checkout` used to be the
        # nearest thing to this, and it does not reach: a clone is its own main checkout,
        # so the check passes and the agent gets its top. See `_agent_caller` for how the
        # caller is named and what happens when it cannot be.
        if (who := _agent_caller(me)) is not None:
            print(f"sb: `sb start` creates a top-level dispatcher, and only a human "
                  f"does that — {who}.\n"
                  f"    An agent that needs another agent delegates one:\n"
                  f"      sb delegate \"<task>\" --role worker", file=sys.stderr)
            return 1
        # Read BEFORE starting, or the one we are about to make is in the list. This is
        # the only thing left standing between "always start another" and losing track of
        # the ones you have: nothing here reuses them, so the way back has to be said.
        others = [] if args.name else b.running_tops()
        name = b.start(name=args.name, task=args.task, model=args.model)
        also = (f"\n  still running: {', '.join(others)}"
                f" — back to one with: sb start --name {others[-1]}") if others else ""
        _emit(args, f"dispatcher '{name}' ready in its own workspace — switch to it, "
                    f"or: sb tell {name} \"...\"{also}",
              {"name": name, "running": others})
        return 0

    if cmd == "delegate":
        # `--with` goes down as NAMES. Resolution and layering live in the broker's
        # `_resolve_bindings`, because this branch is not the only way a spawn happens:
        # `sb workspace new` and `sb start` reach `delegate` directly, and while the
        # layering lived here their leads got nothing bound at all.
        # `--workspace` says WHERE, and only where: the broker resolves the name to the
        # placement keywords `delegate` already takes, so a join spawns through exactly
        # the same call an inheriting child does. Without it, `delegate` inherits the
        # caller's workspace or forks, as it always has.
        join = b.join_workspace(args.workspace) if args.workspace else {}
        name = b.delegate(args.task, role=args.role, as_prompt=args.as_prompt,
                          topic=args.name, isolation=args.isolation,
                          model=args.model, with_=args.with_, me=me, **join)
        where = f" (joined workspace '{args.workspace}')" if args.workspace else ""
        # A spawn can end in three places, not two: confirmed, confirmed-nowhere-but-the
        # agent is plainly running (this note), or raised. The middle one is a name plus a
        # caveat and it must arrive WITH the name — a caller that reads "delegated to w3"
        # and nothing else has been told the delivery was proved, and the note is the
        # difference between that and "something is running; go and look".
        #
        # Exit 0, and deliberately: an agent is up, it has been sent the task three times,
        # and the actions this would otherwise provoke — respawn, force-close — are the
        # expensive ones. See `Broker._took_a_turn`.
        note = b.delivery_note
        _emit(args, f"delegated to {name}{where}" + (f" — {note}" if note else ""),
              {"name": name, "workspace": join.get("workspace"), "unconfirmed": note})
        return 0

    if cmd == "grant":
        r = b.grant(args.agent, args.cap, delegable=args.delegable,
                    reason=args.reason, me=me)
        # The two halves are said apart, because they are two different facts about the
        # recipient and confusing them is the whole reason `--delegable` exists: one says
        # what that agent may now DO, the other says what its children may be SEEDED with
        # while it still may not do it.
        what = (f"may pass {r['cap']} down to agents it spawns (it still does not hold "
                f"{r['cap']} itself)" if r["delegable"] else f"holds {r['cap']}")
        _emit(args, f"{r['agent']} {what} — for the rest of its life; there is no revoke",
              r)
        return 0

    if cmd == "merge":
        r = b.merge(args.child, me=me)
        if r["status"] == "conflict":
            # Exit 0 and a description, not a failure: the merge is UNDERWAY, an agent is
            # resolving it, and the caller's next move is to wait for that agent rather
            # than to retry the command. A non-zero exit here reads as "nothing happened".
            text = (f"{r['child']} ({r['branch']}) conflicts with {r['into']} in "
                    f"{', '.join(r['conflicts'])} — {r['integrator']} is resolving that "
                    f"merge in your checkout. It is left in progress until they finish; "
                    f"merge your next child against the result once they report.")
        elif r["status"] == "up-to-date":
            text = (f"{r['child']} ({r['branch']}) was already in {r['into']} — nothing "
                    f"to fold in.")
        else:
            text = (f"merged {r['child']} ({r['branch']}) into {r['into']} — your branch "
                    f"only: nothing pushed, no pull request opened.")
        _emit(args, text, r)
        return 0

    if cmd == "who-holds":
        holders = b.who_holds(args.cap)
        _emit(args, _who_holds_text(args.cap, holders),
              {"cap": args.cap, "holders": holders})
        return 0

    if cmd == "tell":
        ids = b.tell(args.who, args.message, me=me,
                     needs_reply=args.needs_reply, mode=args.mode)
        # Whether the doorbell actually rang. `tell` used to report plain success even
        # when the ring failed outright, so the sender proceeded believing the handoff had
        # happened — liveness loss, which in an async system is worse than an error.
        #
        # Still exit 0, and deliberately: the message is durable, and the next `sb`
        # command anyone runs re-rings it (see Broker.flush_pending). Being mid-turn is
        # the ordinary reason, not a failure. The report says who has not been told YET.
        mine = [m for m in (store.get_message(db, i) for i in ids) if m is not None]
        undelivered = sorted({m["to_agent"] for m in mine if m["delivered_at"] is None})
        # "will be rung when free" is a promise, and for one of these it is a false one:
        # herdr can lose a live agent's name binding, and then no `sb` command anybody
        # runs will ever ring it again. Saying so is the whole recovery path — a person
        # goes and types in that pane.
        #
        # Asked of every target and not only of the ones still un-announced, because an
        # agent that has finished no longer leaves its mail un-announced: it is stamped on
        # the spot precisely so nothing retries it (`_clear_unreadable_mail`). Reading the
        # note off the undelivered set alone would have printed nothing at all — plain
        # "sent to w2", the same words a delivery gets.
        lost = [n for n in sorted({m["to_agent"] for m in mine}) if b.unreachable(n)]
        waiting = [n for n in undelivered if n not in lost]

        def _has_pane(n: str) -> bool:
            a = store.get_agent(db, n)
            return bool(a and a["pane_id"])

        # The two unreachable populations differ only in what a person can do about it, and
        # that is the whole content of the note: a pane that is still open can be typed in.
        closed = [n for n in lost if not _has_pane(n)]
        lost = [n for n in lost if n not in closed]
        notes = []
        if waiting:
            # Being mid-turn only holds a message back in `--when-idle`; the default rings
            # a working agent on the spot. So the two modes get told different things, and
            # neither is told the other's reason: under the default, a target still waiting
            # is one that has STOPPED for a person, and "mid-turn" would send the sender
            # looking for a turn that is not running.
            why = ("mid-turn or blocked" if args.mode == broker_mod.WHEN_IDLE
                   else "blocked, waiting on the human")
            notes.append(f"{', '.join(waiting)} {why} — will be rung when free")
        if lost:
            notes.append(f"{', '.join(lost)} UNREACHABLE — herdr no longer answers to its "
                         f"name and the doorbell will not ring again; the message is "
                         f"stored and still in its inbox, but somebody has to go to its "
                         f"pane")
        if closed:
            notes.append(f"{', '.join(closed)} has finished and its pane is closed — the "
                         f"message is stored (`sb inspect {closed[0]}`) but nobody will "
                         f"read it")
        note = f" ({'; '.join(notes)})" if notes else ""
        _emit(args, f"sent to {', '.join(args.who)}{note}",
              {"ids": ids, "undelivered": waiting, "unreachable": lost + closed,
               "closed": closed})
        return 0

    if cmd == "inbox":
        if me == HUMAN:
            # A person has no mailbox — an agent that needs you blocks instead, and the
            # block waits on the board until you answer it. Saying so beats printing
            # "(no new messages)", which reads as "nothing needs you" and is a different
            # claim entirely. The board, not `sb status`: `sb board` is the human's
            # surface (DESIGN-TRUTH.md), and a blocked agent is a marked row there
            # carrying its reason (`board.wants_you`, `board.marker`).
            _emit(args,
                  "you have no inbox — agents that need you BLOCK, and a blocked agent "
                  "waits on `sb board` as a marked row with its reason (answer with "
                  "`sb tell <agent> \"...\"`)",
                  {"messages": [], "human": True})
            return 0
        msgs = b.inbox(me=me, peek=args.peek)
        if not msgs:
            _emit(args, "(no new messages)", {"messages": []})
            return 0
        # A `--needs-reply` message reads exactly like any other until this line: the flag
        # is a claim on the reader, and the reader only ever meets it here. Appended as its
        # own line under the message rather than folded into the body, so the body stays
        # what the sender typed.
        lines = []
        for m in msgs:
            # `broker.tag`, not a second spelling of it: this line and the doorbell that
            # sent the reader here are the same claim about the same message, and they used
            # to disagree — `[3] from w1:` here, no sender at all there.
            lines.append(f"[{m['id']}] {broker_mod.tag(m['from_agent'])} {m['body']}")
            if _needs_reply(m):
                lines.append("    " + config.prompt("notify.needs_reply", b.repo,
                                                    who=m["from_agent"]))
        _emit(args, "\n".join(lines),
              {"messages": [dict(m) for m in msgs]})
        return 0

    if cmd == "done":
        still = b.done(args.summary, me=me)
        # Legal, and worth saying out loud: the agent is finishing a turn its children
        # have not finished, and their summaries will arrive here after it.
        note = "done" if not still else (
            "done — still working underneath you: " + ", ".join(still)
            + ". Their summaries will reach you here, and nothing will close your pane "
              "while they run.")
        if b.done_repeat:
            # Not a failure — exit 0, and the text says what was and was not done. An
            # agent told only "already done" reaches for a way to make it stick; an agent
            # told its report is recorded and its parent already has the first one has
            # nothing left to do.
            note = ("already reported — you called `sb done` before, and your parent has "
                    "that summary. This one is recorded in the log, but it is not sent "
                    "again and the first summary stays on the board. Nothing to redo.")
        _emit(args, note, {"agent": me, "live_children": still,
                           "repeat": b.done_repeat})
        return 0

    if cmd == "block":
        b.block(args.why, me=me)
        # Says WHAT they read, not just that they were told. The old note ("they will see
        # it") let a caller believe the reason was the delivered message, which is the
        # misuse validate.reason now refuses. "The board", not `sb board`: this is read by
        # an agent, and the verb is deliberately not part of an agent's vocabulary (see
        # the human-only refusal in `board` above, and the shipped prompts, which say
        # "a board row" and never name the command).
        _emit(args, "blocked — your reason marks your row on the human's board until "
                    "they answer; what they actually read is your own chat, so the full "
                    "question belongs there", {"agent": me})
        return 0

    if cmd == "status":
        # Straight to the module, like `output`: this reads the store and herdr side by
        # side and belongs to neither. The whole tree, not just the caller's children —
        # drift two levels down is still drift the caller is being lied to about.
        # THE TREE BOUNDARY. An agent sees its own top's whole tree and no other's;
        # the human sees everything. `--mine` still means the caller's own subtree, which
        # is narrower — the flag asks for less, and cannot ask for more.
        snap = status_mod.collect(db, h, live_only=args.live, needs_me=args.needs_me,
                                  # THIS repo's role definitions: the ROLE column reads
                                  # divergence against the same templates the spawn seeded
                                  # from, and a repo that redefined a bundle must not have
                                  # its rows measured against the shipped one.
                                  repo=b.repo, **_scope(b, me, args.mine))
        # None, not False: the flag can only ever turn collapse OFF, so with no flag the
        # answer comes from `display.show_archived` rather than from here.
        _emit(args, status_mod.render(snap, show_archived=True if args.archived else None),
              snap.as_dict())
        return 0

    if cmd == "presets":
        if args.name:
            try:
                if args.apply:
                    # The text goes to the caller's own session, so what is printed here is
                    # a receipt, not the preset: printing both would deliver it twice, once
                    # as output and once as the message that is the point of the verb.
                    mid = b.apply_preset(args.name, me=me)
                    _emit(args, f"applied preset '{args.name}' to this session",
                          {"preset": args.name, "applied": True, "message_id": mid})
                    return 0
                path, body = presets_mod.text(b.repo, args.name)
            except KeyError:
                # Name the alternatives rather than just refusing: the caller is an agent
                # that was told to follow a procedure and got the name slightly wrong, and
                # the whole list is four items long.
                known = ", ".join(sorted(presets_mod.available(b.repo))) or "none"
                print(f"sb: no preset '{args.name}' (have: {known})", file=sys.stderr)
                return 1
            _emit(args, body.rstrip("\n"),
                  {"preset": args.name, "path": str(path), "text": body})
            return 0
        if args.apply:
            # Listing is what a bare `sb presets` does, and applying "all of them" is not a
            # thing. Refused here rather than silently listing, because the caller asked
            # for a side effect and would otherwise be told nothing happened by being shown
            # something that looks like success.
            print("sb: --apply needs a preset name — `sb presets` lists them",
                  file=sys.stderr)
            return 2
        found = presets_mod.available(b.repo)
        every, per_role = presets_mod.bindings(b.repo)
        lines = []
        for n in found:
            using = [r for r, ps in per_role.items() if n in ps]
            tag = " [every agent]" if n in every else (f" [{', '.join(using)}]" if using else "")
            lines.append(f"  {n:16}{tag}")
        _emit(args, "\n".join(lines) or f"(none — add {_preset_dir_help()}<name>.md)",
              {"presets": sorted(found), "all": list(every),
               "roles": {k: list(v) for k, v in per_role.items()}})
        return 0

    if cmd == "plugin":
        return _plugin_list(args, b) if args.name == "list" else _plugin_run(args, b, db, me)

    if cmd == "models":
        tiers = models_mod.load(b.repo)
        rows = [(n, tiers.resolve(n)) for n in tiers.names()]
        # The flags column is what actually reaches the provider CLI, so it is what gets
        # shown. THREE rows read as empty for different reasons and must not look alike: a
        # tier with neither model nor effort is deferring to the CLI's own default (a
        # choice); a codex tier has a model and an effort and simply does not deliver them
        # as flags (they are keys in a private per-agent `CODEX_HOME/config.toml` —
        # `switchboard/codex.py`), so printing "(provider default)" there would say the
        # opposite of what is true; and an unwired provider cannot be spawned at all. The
        # last is legal config — models.py keeps `provider` real ahead of its backend — so
        # it is reported per row rather than allowed to take the whole listing down, since
        # finding out WHICH tier is unspawnable is why anyone runs this.
        out: dict[str, dict] = {}
        lines = []
        for n, s in rows:
            try:
                flags, note = s.cli_args(), ""
            except models_mod.ModelConfigError as e:
                flags, note = [], f"UNAVAILABLE — {e}"
            out[n] = {"provider": s.provider, "model": s.model, "effort": s.effort,
                      "cli_args": flags, "error": note or None}
            settings = " ".join(
                x for x in (f"model {s.model}" if s.model else "",
                            f"effort {s.effort}" if s.effort else "") if x)
            shown = note or " ".join(flags) or (
                f"{settings} (in the agent's codex home)" if settings
                else "(provider default)")
            lines.append(f"  {n:12}{s.provider:10}{shown}")
        _emit(args, "\n".join(lines),
              {"default_provider": tiers.default_provider, "tiers": out})
        return 0

    if cmd == "cleanup":
        names = b.cleanup(args.name, force=args.force, dry_run=args.dry_run, me=me)
        verb = "would close" if args.dry_run else "closed"
        text = f"{verb}: {', '.join(names) or '(nothing)'}"
        # Named agents always get every reason, because naming one is asking about it in
        # particular — and so does a sweep that closed NOTHING, where the refusals are
        # the entire outcome.
        #
        # A sweep that closed SOMETHING used to print no refusals at all, and that was
        # the same silence in a better disguise: `closed: five names` reads as "all
        # done", and twice in acceptance run 4 the row it left out was the one the human
        # needed. The whole fleet is not the answer either — a sweep skips most of it by
        # design, so listing every skip grows with
        # the fleet and buries the line that matters. So it reports `refused.notable`:
        # rows already closed and agents merely working are the sweep working as intended
        # and stay quiet, everything else gets its name and its reason. `--json` is
        # unchanged and still carries every refusal of either kind.
        if names.refused and (args.name or not names):
            text += "\n" + "\n".join(f"  refused {n}: {why}" for n, why in names.refused)
        elif names.notable:
            text += "\n" + _sweep_refusals(names.notable)
        # A deleted worktree is always news, so closed spaces get a line whenever there
        # are any. The spaces left standing are not: a sweep looks at every space its
        # scope touches and most of them are held back by an agent still working in them,
        # which the lines above already said. So they go to `--json` always, and to the
        # text only when the caller named agents outright — the shape where they asked
        # about something in particular and silence would be a lie.
        if names.spaces:
            verb = "would close" if args.dry_run else "closed"
            text += f"\n  {verb} space(s): {', '.join(names.spaces)}"
        if names.spaces_refused and args.name:
            text += "\n" + "\n".join(f"  kept space {n}: {why}"
                                     for n, why in names.spaces_refused)
        _emit(args, text,
              {"closed": list(names),
               "refused": [{"name": n, "reason": why} for n, why in names.refused],
               "expected": sorted(names.expected),
               "spaces": list(names.spaces),
               "spaces_refused": [{"name": n, "reason": why}
                                  for n, why in names.spaces_refused]})
        return 0

    if cmd == "sweep":
        # Human-only, and gated the same way `board` is rather than merely hidden: this
        # deletes checkouts across the whole fleet, which is nobody's subtree. The board
        # that runs it on a schedule is a human's pane and resolves to the human here.
        if me != broker_mod.HUMAN:
            print(f"sb: sweep is the human's housekeeping; you are '{me}'.\n"
                  f"    `sb cleanup` is yours, and it is scoped to your own subtree.",
                  file=sys.stderr)
            return 1
        d = b.sweep(dry_run=args.dry_run)
        verb = "would delete" if args.dry_run else "deleted"
        text = f"{verb}: {', '.join(d['swept']) or '(nothing)'}"
        if d.get("stopped"):
            text = f"nothing swept: {d['stopped']}"
        # Every held space gets a line, unlike `cleanup`'s sweep, which stays quiet about
        # the ordinary ones. This is the readout that has to name the three worktrees
        # holding unpushed code every half hour until somebody deals with them, and a
        # sweep that printed only what it deleted would be the silence this whole change
        # is about. It is a hidden verb a person types, not something an agent reads.
        for h in d["held"]:
            text += f"\n  kept {h['name']}: {h['reason']}"
        text += f"\n({d['looked']} worktree(s) looked at)"
        _emit(args, text, d)
        return 0

    if cmd == "workspace" and args.wcmd == "list":
        d = b.workspace_list()
        _emit(args, _workspace_listing(d), d)
        return 0

    if cmd == "workspace" and args.wcmd == "close":
        r = b.workspace_close(args.name, me=me, resume=args.resume, confirm=args.confirm)
        # Reshaped for `--json` on BOTH exits and not only the one that can fill the
        # list today: two shapes for one key, decided by which branch was taken, is a
        # divergence waiting for the day something fills it on the `already` route.
        out = {**r, "spaces_refused": [{"name": n, "reason": why}
                                       for n, why in r["spaces_refused"]]}
        if r["already"]:
            _emit(args, f"{r['workspace']} was retired already — nothing left to do", out)
            return 0
        _emit(args, _workspace_closed(r), out)
        return 0

    if cmd == "restore" and args.sweep:
        r = b.restore_sweep(dry_run=args.dry_run, me=me)
        _emit(args, _sweep_restored(r, dry_run=args.dry_run),
              {"restored": list(r),
               "skipped": [{"name": n, "reason": why} for n, why in r.skipped],
               "unrestorable": [{"name": n, "reason": why}
                                for n, why in r.unrestorable],
               "failed": [{"name": n, "reason": why} for n, why in r.failed],
               "dry_run": args.dry_run})
        return 0

    if cmd == "restore":
        b.restore(args.name, me=me)
        # The capability note, when there is one. A restored agent comes back on its
        # stored seed and its grants are gone — a narrowing the operator can put right in
        # one line, and cannot if nobody says it happened. The agent is told the same
        # thing through its inbox (`Broker._reseed_on_restore`).
        note = b.restore_note
        _emit(args, f"restored {args.name}" + (f" — {note}" if note else ""),
              {"name": args.name, "capabilities": note})
        return 0

    if cmd == "inspect":
        # Straight to the module, like `status`: this reads the store and herdr side by
        # side and belongs to neither. It subsumes the old `sb output` — output.py is still
        # the reader underneath, it is just no longer a verb of its own, because "show me
        # the terminal" was never really the question anyone had.
        # Refused across the tree boundary before anything is read: `inspect` is the
        # widest read in the CLI (task, transcript, events) and takes a bare name.
        b.require_same_tree(me, args.name)
        d = status_mod.inspect(db, h, args.name, lines=args.n, events=args.events,
                               repo=b.repo)
        _emit(args, status_mod.render_detail(d), d.as_dict())
        return 0

    if cmd == "log":
        if args.agent:
            b.require_same_tree(me, args.agent)
        rows = store.recent_events(db, agent=args.agent, limit=args.n)[::-1]
        if me != HUMAN:
            # The unfiltered log is every tree's. An event with no agent belongs to the
            # machine rather than to anybody's tree, so it stays: hiding it would say a
            # store-wide failure happened in somebody else's tree, which is not true.
            rows = [r for r in rows if not r["agent"] or b.same_tree(me, r["agent"])]
        lines = [f"{r['id']:5} {r['agent'] or '-':16} {r['kind']:18} {(r['payload'] or '')[:80]}"
                 for r in rows] or ["(no events)"]
        _emit(args, "\n".join(lines), {"events": [dict(r) for r in rows]})
        return 0

    return 2


_SWEEP_REFUSALS_SHOWN = 5


def _sweep_refusals(notable: list[tuple[str, str]]) -> str:
    """What a sweep that closed something still has to say about what it did not.

    Named and reasoned, like every other refusal, because "one row was left behind" that
    does not say WHICH row sends the human back to `sb status` to find it. Bounded,
    because a sweep is the one shape of this command whose refusal list scales with the
    fleet: past a handful the lines stop being a report and start being a listing, and
    the tail is one line saying so rather than a hundred saying it individually.

    The cut is `CleanupResult.notable`, made in the broker where the gates are — so this
    is only formatting, and the decision about what counts as news lives next to the code
    that knows why a row was held.
    """
    shown = notable[:_SWEEP_REFUSALS_SHOWN]
    lines = [f"  refused {n}: {why}" for n, why in shown]
    rest = len(notable) - len(shown)
    if rest:
        lines.append(f"  … and {rest} more refused — `sb cleanup --json` lists them all")
    return "\n".join(lines)


def _sweep_restored(r, *, dry_run: bool) -> str:
    """One line per row the sweep considered, then a count.

    Every candidate gets a line, and nothing is truncated the way `_sweep_refusals`
    truncates: a crash cohort is bounded by the crash, not by the fleet, and this is read
    once right after a scary event by somebody who wants the list rather than a number.
    The two things that must be legible without re-reading are which agents came back and
    which ones nothing can bring back — so the unrestorable rows are last, where the eye
    stops, rather than buried between the successes.

    The summary line names the scope out loud. A sweep an agent ran saw its own subtree,
    and a count with no scope on it reads as "the fleet is back" when it may be a third
    of it.
    """
    lines = [f"would restore {n}" if dry_run else f"restored {n}" for n in r]
    lines += [f"already running, skipped {n}" for n, _ in r.skipped]
    # "failed" is what it is called once something was attempted. In a preview nothing
    # was, so the same row says what it would run into rather than claiming an error.
    lines += [(f"would not restore {n}: {why}" if dry_run else f"restore failed: {n}: {why}")
              for n, why in r.failed]
    lines += [f"cannot restore {n}: {why}" for n, why in r.unrestorable]
    if not lines:
        return ("nothing has gone down recently in your scope — nothing to restore. "
                "(An agent that crashed longer ago is still `sb restore <name>`.)")
    verb = "would restore" if dry_run else "restored"
    lines.append(f"{verb} {len(r)} of {r.considered} considered"
                 + (f"; {len(r.unrestorable)} cannot be restored at all"
                    if r.unrestorable else ""))
    return "\n".join(lines)


def _workspace_closed(r: dict) -> str:
    """What `sb workspace close` actually did, named rather than implied.

    Which of the three routes the workspace took is the first thing to say, because "bare"
    doing nothing to a directory and "worktree" deleting one are the same word otherwise.
    A branch left behind is said out loud with the reason: it stays forever, and a person
    who does not know that is a person who thinks the cleanup finished. Two reasons it can
    be left, and they are not the same news — git refusing an unmerged branch is one, and
    nothing being able to NAME the branch is the other, which leaves a person looking for
    a branch this command never identified.
    """
    lines = []
    if r["closed"]:
        lines.append(f"closed {len(r['closed'])} pane(s): {', '.join(r['closed'])}")
    if r["kind"] == "bare":
        # "nothing was deleted" only while that is still true of the whole command. The
        # cascade made `bare` a route that destroys directories — somebody else's, one
        # indented line further down — and a headline sentence written to keep "bare" and
        # "worktree" apart becomes the wrong half of a contradiction the moment it is not
        # revisited. The word `deleted` belongs where deletion happened.
        if r["spaces"]:
            lines.append(f"retired {r['workspace']} — no checkout of its own, and "
                         f"{len(r['spaces'])} forked space(s) below it DELETED")
        else:
            lines.append(f"retired {r['workspace']} — no checkout of its own, so nothing "
                         f"was deleted")
    else:
        lines.append(f"retired {r['workspace']}: worktree {r['worktree']}")
        if not r["branch"]:
            lines.append(f"  no branch deleted — nothing recorded one for "
                         f"{r['workspace']} and git named none for its checkout, and a "
                         f"branch is not guessed at from a workspace name")
        elif not r["branch_deleted"]:
            lines.append(f"  branch {r['branch']} kept — git will not delete an unmerged "
                         f"branch, and it stays until somebody decides otherwise")
    # The cascade, in `cleanup`'s own words because it is `cleanup`'s own machinery: a
    # bare orchestrator's children forked spaces of their own, and what happened to them
    # is not implied by "retired <name>". Both halves get a line, unlike the sweep's
    # quiet one — this is a command a person typed about one named workspace, and a space
    # left standing is the thing they will trip over later.
    if r["spaces"]:
        lines.append(f"  deleted space(s): {', '.join(r['spaces'])}")
    lines.extend(f"  kept space {n}: {why}" for n, why in r["spaces_refused"])
    return "\n".join(lines)


def _workspace_listing(d: dict) -> str:
    """`sb workspace list` as text: one line per workspace, and the path under it.

    The columns are the questions somebody tidying up actually has: is the checkout still
    there, is anything running in it, what is in it that git does not track, and what will
    be left behind if it goes. `unknown` in the live column is not `clear` — a scan that
    could not be made is not the answer "nobody is in there", and printing them the same
    way is how a person comes to believe the wrong one.
    """
    lines = []
    if d["gap"]:
        lines += ["  the workspace records are incomplete, so this listing is not the "
                  "whole story:", f"  {d['gap']}", ""]
    lines.append(f"  {'workspace':<20}{'checkout':<10}{'rows':<12}{'live':<10}"
                 f"{'ignored':<9}left behind")
    for w in d["workspaces"]:
        rows = f"{w['rows']['total']}"
        if w["rows"]["unfinished"]:
            rows += f" ({w['rows']['unfinished']} busy)"
        live = {"clear": "-", "unknown": "UNKNOWN", "skipped": ""}.get(
            w["live_verdict"], f"{len(w['live'])} here")
        ign = "" if w["ignored"] is None else (
            "?" if w["ignored"]["unknown"] is None else str(w["ignored"]["unknown"]))
        left = []
        if w["branch"]:
            left.append("branch UNMERGED" if w["unmerged"] else "branch")
        if w["prunable"]:
            left.append("worktree registered but gone")
        if w["retiring"]:
            left.append(f"being closed by {w['retiring']}")
        left.append("+".join(w["sources"]))
        lines.append(f"  {w['name']:<20}{w['verdict']:<10}{rows:<12}{live:<10}"
                     f"{ign:<9}{', '.join(left)}")
        if w["checkout"]:
            lines.append(f"    {w['checkout']}")
    return "\n".join(lines)


def _plugin_list(args, b: Broker) -> int:
    """`sb plugin list` — every available plugin and how far sb got with it.

    Level 3: each one is imported, and each import is wrapped. One plugin with a
    SyntaxError is a row saying so, and costs the others nothing. `SB_DEBUG=1` prints the
    tracebacks after the table rather than instead of it, so a broken plugin never hides
    the working ones.
    """
    rows = plugins_mod.load_all(b.repo)
    binds = plugins_mod.bound(b.repo)
    lines, tracebacks = [], []
    for p in rows:
        tags = ["enabled" if p.enabled else "not enabled"]
        if p.name in binds:
            tags.append(f"@{p.name} bound to {', '.join(binds[p.name])}")
        note = p.error or f"[{', '.join(tags)}]"
        lines.append(f"  {p.name:<14}{p.version:<8}{p.status:<14}{note}")
        if p.traceback:
            tracebacks.append(f"--- {p.name}\n{p.traceback}")
    if tracebacks and os.environ.get("SB_DEBUG"):
        print("\n".join(tracebacks), file=sys.stderr)
    _emit(args, "\n".join(lines) or f"(no plugins — a plugin is a directory in "
                                    f"{_plugin_dir_help()} with an __init__.py)",
          {"plugins": [p.as_dict() for p in rows],
           "enabled": list(plugins_mod.enabled(b.repo))})
    return 0


class _PluginReport(NamedTuple):
    """What `sb doctor` has to say about plugins: what is wrong, and what is merely so."""

    problems: list[str]
    notices: list[str]
    data: dict

    @property
    def text(self) -> str:
        return "".join(f"\n  {'PROBLEM' if kind else 'note'}  {line}"
                       for kind, group in ((1, self.problems), (0, self.notices))
                       for line in group)


def _doctor_plugins(repo) -> _PluginReport:
    """The four plugin questions `doctor` answers, and which of them are problems.

    **Problems** — a plugin that will not import, and one targeting an API this sb does not
    support. Both mean a command an agent may have been told to run does not exist, and
    incompatibility in particular is not caught at spawn time by design (§11 item 4): the
    fragment is injected anyway, because `delegate` never imports, so this is the only place
    the mismatch is visible before an agent trips over it.

    **Notices** — an orphaned state directory (§5.6), a plugin sb is importing out of the
    repo rather than out of `defaults/`, and the pre-rename spellings of §8.2. None of these
    is broken; all three are things a person should know and cannot otherwise see.

    The repo-sourced note is visibility, not a gate. There is no trust prompt and no content
    pinning, because the party who can write `.switchboard/plugins/` can already run code on
    this machine through `conftest.py`, a `Makefile`, or a git hook. What `doctor` adds is
    that you find out sb is importing it.
    """
    problems, notices = [], []
    rows = plugins_mod.load_all(repo)
    for p in rows:
        if p.status in ("broken", "incompatible"):
            problems.append(f"plugin '{p.name}' {p.status}: {p.error}")
        elif p.source == "repo":
            notices.append(f"plugin '{p.name}' is loaded from {_plugin_dir_help()}, "
                           f"not from defaults/ — sb imports it as-is")
    orphans = plugins_mod.orphans(repo)
    for o in orphans:
        notices.append(f"orphaned plugin state: {o.path}/  (no such plugin; "
                       f"rm -rf to discard)")
    deprecated = presets_mod.deprecations(repo)
    notices.extend(deprecated)
    return _PluginReport(problems, notices, {
        "plugins": [p.as_dict() for p in rows],
        "plugin_problems": problems,
        "orphaned_state": [o.as_dict() for o in orphans],
        "deprecations": deprecated,
    })


def _plugin_dir_help() -> str:
    return "{}/{}/".format(config.setting("paths.repo_dir"),
                           config.setting("paths.plugins_dir"))


def _plugin_run(args, b: Broker, db, me: str) -> int:
    """`sb plugin <name> <verb> …` — level 4, the only level that invokes a handler.

    `audience` is enforced here rather than inside the plugin: declared once, and
    impossible for a plugin author to forget (C6). The refusal names what to do instead,
    the same treatment a message addressed to the human gets.
    """
    p, c = args.plugin, args.command
    agent = None if me == HUMAN else me
    if c.audience == "human" and agent is not None:
        print(f"sb: `{p.name} {c.name}` is for the human, and you are '{me}'.\n"
              f"    Ask for it with `sb block \"...\"`, which surfaces to them.",
              file=sys.stderr)
        return 1
    if c.audience == "agent" and agent is None:
        print(f"sb: `{p.name} {c.name}` is for agents, and you are the human.\n"
              f"    Run `sb plugin {p.name} --help` for what is meant for you.",
              file=sys.stderr)
        return 1

    d = plugins_mod.state_dir(p, b.repo)
    ctx = plugins_mod.Context(
        api=plugins_mod.API, name=p.name, state_dir=d, repo=store.repo_root(b.repo),
        worktree=b.repo, agent=agent, json=bool(args.json))
    try:
        # sb holds the lock, so a plugin doing read-modify-write on a JSON file is correct
        # without its author knowing the word "lock". Around the handler and nothing else.
        with plugins_mod.locked(d, p.lock):
            r = plugins_mod.run(p, c, ctx, args.pargs)
    except plugins_mod.PluginError:
        _log_plugin(db, agent, p.name, c.name, ok=False)
        raise
    # One event per handler invocation, written by sb on the plugin's behalf: plugin,
    # command, ok. Plugins get no database handle of their own, and this is why they do not
    # need one to show up in `sb log` beside agent activity.
    _log_plugin(db, agent, p.name, c.name, ok=r.ok)

    payload = {"ok": r.ok, "plugin": p.name, "command": c.name, "data": r.data}
    if r.ok:
        _emit(args, r.human, payload)
    elif args.json:
        _emit(args, "", payload)
    elif r.human:
        print(r.human, file=sys.stderr)
    # The plugin's own exit status to spend. A handler that reported failure and no code
    # still has to be non-zero, or `sb plugin … && …` in a shell means the wrong thing.
    return r.code or (0 if r.ok else 1)


def _log_plugin(db, agent: Optional[str], plugin: str, command: str, *, ok: bool) -> None:
    store.log_event(db, kind="plugin", agent=agent, plugin=plugin, command=command, ok=ok)


if __name__ == "__main__":
    raise SystemExit(main())
