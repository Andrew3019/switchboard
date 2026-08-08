"""The `sb` command — the only surface agents ever see.

Seven verbs for agents (`delegate`, `ask`, `tell`, `inbox`, `done`, `block`, `status`), a
few more for the human (`init`, `doctor`, `cleanup`, `restore`, `interrupt`, `inspect`,
`wait`, `log`, `presets`, `models`, `workspace`), and `plugin`, which is a namespace rather
than a verb: `sb plugin <name> <verb>` is whatever a plugin declared, and `sb plugin list`
says what this repo has.

`wait` is the one verb that is *only* for a human: an agent that blocks on a child is
burning a turn to do what the doorbell already does for free (see broker.done). It says so
in its own help, because that is where anyone about to misuse it is looking.

Every command takes `--json`, on either side of the subcommand, so wrapping this in an MCP
server later is mechanical (C13). It was global-only for a while, which cost a QA run its
first three spawn attempts; `tests/test_status.py` now builds the check from the parser's
own subcommand list so a verb added later cannot quietly miss it.

Arguments are checked here and nowhere else (see `_validate` and validate.py). This is
the last point where an error can name the flag the caller typed: below it, a bad value
comes back as a herdr error code, or as an `ask` that blocks for its whole timeout.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Any, NamedTuple, Optional

from . import config
from . import models as models_mod
from . import panel as panel_mod
from . import plugins as plugins_mod
from . import presets as presets_mod
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

    st = cmd("start", help="start (or return to) the top-level orchestrator")
    st.add_argument("task", nargs="?", help="optional first instruction")
    st.add_argument("--name", help="explicit name (implies a distinct orchestrator)")
    st.add_argument("--new", action="store_true", help="always start another one")
    st.add_argument("--no-focus", dest="focus", action="store_false")
    st.add_argument("--no-board", dest="board", action="store_false",
                    help="do not open the clickable board beside it")

    # Hidden on purpose. The board is a human's screen, and `sb` is the vocabulary
    # agents are handed — see the refusal in main(). SUPPRESS keeps it out of
    # `sb --help`, and it is absent from defaults/protocol.md, which is where an
    # agent actually learns what `sb` can do. `python3 -m switchboard.board` stays
    # the equivalent, unhidden way in.
    cmd("board", hidden=True)

    d = cmd("delegate", help="spawn a child agent to do a task")
    d.add_argument("task")
    d.add_argument("--role", default=broker_mod.DEFAULT_ROLE)
    d.add_argument("--as", dest="as_prompt", help="ad-hoc role prompt instead of a named role")
    d.add_argument("--with", dest="with_", action="append", default=[], metavar="PRESET",
                   help=f"preset from {_preset_dir_help()}, or @<plugin> for that plugin's "
                        f"fragment (repeatable); an unknown BARE value is used as a literal "
                        f"instruction, but @ is reserved and an unknown @name is an error")
    d.add_argument("--name")
    d.add_argument("--workspace", metavar="NAME",
                   help="join this EXISTING workspace instead of working where you are "
                        "(open one with: sb workspace new <name>)")
    d.add_argument("--model", help=_tier_help())
    d.add_argument("--keep", action="store_true", help="do not auto-close when finished")
    d.add_argument("--ephemeral", action="store_true", help="close as soon as it finishes")

    a = cmd("ask", help="send a question and WAIT for the answer")
    # Agents only. `human` is still an accepted SHAPE here (validate.target) so the broker
    # can answer it with a sentence naming `sb block`, rather than argparse answering it
    # with a usage dump that teaches nobody anything.
    a.add_argument("who", nargs="+", help="agent name(s) or 'parent' — not the human, "
                                          "who is reached with `sb block`")
    a.add_argument("question")
    a.add_argument("--timeout", type=int, default=broker_mod.ASK_TIMEOUT)

    t = cmd("tell", help="send a message, do not wait")
    t.add_argument("who", nargs="+")
    t.add_argument("message")
    t.add_argument("--re", dest="reply_to", type=int, help=argparse.SUPPRESS)

    # Agents only. A human has no mailbox — see the `inbox` branch in `run`.
    ib = cmd("inbox", help="read your unread messages")
    ib.add_argument("--peek", action="store_true",
                    help="do not mark as read (safe for polling)")

    dn = cmd("done", help="you have finished")
    dn.add_argument("summary")

    bl = cmd("block", help="stop and surface to the human (they answer with `sb tell`)")
    bl.add_argument("why")

    ss = cmd("status", help="the agent tree, with drift and what needs you")
    # `--live` is the older spelling of the same want and stays forever: it is in scripts,
    # and in muscle memory. One dest, so they can never disagree.
    ss.add_argument("--active", "--live", dest="live", action="store_true",
                    help="hide finished agents")
    ss.add_argument("--needs-me", dest="needs_me", action="store_true",
                    help="only agents that are blocked, at a prompt, or holding unread mail")
    ss.add_argument("--mine", action="store_true",
                    help="only your own subtree (for a human: every agent)")
    # Naming one prints it. A preset is not always a disposition stapled onto a spawn —
    # some are procedures an agent is TOLD to go and follow, and without a way to read one
    # on demand the only way to reach a procedure was to be spawned with it already
    # attached, paying its length on every such spawn forever. Read-only, load level 1, no
    # plugin import: safe for an agent to run mid-turn.
    pr = cmd("presets", help="list available presets, or print one")
    pr.add_argument("name", nargs="?", help="print this preset instead of listing")
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
        "cleanup", help="close finished agents",
        description="With no name, closes every finished agent in your subtree (for a "
                    "human: all of them). Naming agents closes those instead, and a name "
                    "also means you want it closed whatever disposition it was spawned "
                    "with.")
    c.add_argument("name", nargs="*", help="specific agents to close")
    # `--all-idle` is the older spelling and stays forever: it is in scripts and in muscle
    # memory. One dest, so the two can never disagree. The newer name is the honest one —
    # this has never closed agents by idleness, only agents that FINISHED, and the old
    # name promised a sweep by idleness that would close an agent mid-turn.
    c.add_argument("--include-kept", "--all-idle", dest="include_kept", action="store_true",
                   # No role carries a disposition any more — it is set per spawn by
                   # `sb delegate --keep` / `--ephemeral` and stored on the agent. The help
                   # said "whose role says keep" long after roles stopped saying anything.
                   help="also close finished agents that were spawned to be kept")
    c.add_argument("--force", action="store_true",
                   help="close a NAMED agent whatever state it is in, unread mail and all "
                        "(the escape hatch for one that is genuinely stuck)")
    c.add_argument("--dry-run", action="store_true")

    w = cmd("workspace", help="workspaces (worktree + herdr workspace + lead)")
    wsub = w.add_subparsers(dest="wcmd", required=True)
    wn = wsub.add_parser("new", parents=[common], help="open a workspace, creating it if absent")
    wn.add_argument("name", nargs="?", help="defaults to the checkout you are in")
    wn.add_argument("--task", help="first instruction for the lead agent")
    wn.add_argument("--role", default=broker_mod.WORKSPACE_ROLE)
    # `--name` everywhere an agent is being named — `sb start --name`, `sb delegate --name`,
    # and this. `--agent` was the odd one out and stays as an alias on the same dest, the
    # same way `sb status --live` does.
    wn.add_argument("--name", "--agent", dest="agent", help="name for the lead agent")
    wn.add_argument("--base", default=broker_mod.BASE_BRANCH,
                    help="branch to fork the worktree from")
    wn.add_argument("--focus", action="store_true")
    wn.add_argument("--no-board", dest="board", action="store_false",
                    help="do not open the clickable board beside the lead")

    r = cmd("restore", help="bring a closed agent back with its context")
    r.add_argument("name")

    i = cmd("interrupt", help="change an agent's course mid-flight")
    i.add_argument("name")
    i.add_argument("text")

    ins = cmd(
        "inspect", help="everything about ONE agent, including its recent terminal output",
        description="What is going on with this agent: its task, state, drift, workspace, "
                    "mail (including any ask nobody has answered), last summary, recent "
                    "events, and the tail of its terminal — live pane if it has one, the "
                    "on-disk transcript if it does not.")
    ins.add_argument("name")
    ins.add_argument("-n", type=int, default=status_mod.DEFAULT_LINES,
                     help="lines of terminal output to show")
    ins.add_argument("--events", type=int, default=status_mod.DEFAULT_EVENTS,
                     help="how many recent events to include")

    wt = cmd(
        "wait", help="block until an agent reaches a state (for HUMANS, not agents)",
        description="For a human at a terminal, or a shell script. Agents must NOT use "
                    "this: end your turn instead and you will be poked the moment a child "
                    "reports — waiting burns a turn to do what the doorbell does free. "
                    "Exits non-zero if the timeout runs out or the agent finishes some "
                    "other way.")
    wt.add_argument("name")
    wt.add_argument("--for", dest="until", default="done", choices=status_mod.WAIT_STATES,
                    help="state to wait for (default: done)")
    wt.add_argument("--timeout", type=int, default=status_mod.WAIT_TIMEOUT,
                    help=f"seconds (default: {status_mod.WAIT_TIMEOUT})")

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

    elif cmd == "delegate":
        args.task = validate.line(args.task, "task")
        # Not slugified here: the role is also a lookup key into roles.toml, and a role
        # nobody defined is legal (roles.get falls back to worker). Only the agent NAME
        # derived from it has to satisfy herdr — see _derived_name.
        args.role = validate.line(args.role, "--role", max_len=validate.MAX_TOKEN)
        if args.name is not None:
            args.name = validate.agent_name(args.name, "--name")
        # A workspace name IS a branch name, so it is checked as one — the same rule
        # `sb workspace new` is held to, since both name the same place.
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

    elif cmd == "ask":
        args.who = validate.targets(args.who)
        args.question = validate.text(args.question, "question")
        args.timeout = validate.positive_int(args.timeout, "--timeout")

    elif cmd == "tell":
        args.who = validate.targets(args.who)
        args.message = validate.text(args.message, "message")

    elif cmd == "done":
        # herdr carries the summary as `report-agent --message`, so one line.
        args.summary = validate.line(args.summary, "summary")

    elif cmd == "block":
        args.why = validate.line(args.why, "reason")

    elif cmd == "workspace":
        if args.name is not None:
            args.name = validate.ref_name(args.name)
        args.base = validate.ref_name(args.base, "--base")
        args.role = validate.line(args.role, "--role", max_len=validate.MAX_TOKEN)
        if args.agent is not None:
            args.agent = validate.agent_name(args.agent, "--agent")
        if args.task is not None:
            args.task = validate.line(args.task, "--task")

    elif cmd == "restore":
        args.name = validate.agent_name(args.name)

    elif cmd == "interrupt":
        args.name = validate.agent_name(args.name)
        args.text = validate.line(args.text, "text")

    elif cmd == "inspect":
        args.name = validate.agent_name(args.name)
        args.n = validate.positive_int(args.n, "-n")
        args.events = validate.positive_int(args.events, "--events")

    elif cmd == "wait":
        args.name = validate.agent_name(args.name)
        args.timeout = validate.positive_int(args.timeout, "--timeout")

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


def _derived_name(db, role: str) -> Optional[str]:
    """The agent name the broker would derive from this role, made legal — or None.

    The broker names an unnamed child `<role>-<n>`, so `--role "QA Bot"` would ask herdr
    for the agent `QA Bot-1` and be refused. Slugifying the role itself is not an option
    (it is also the roles.toml lookup key), so the name is derived here instead, from the
    slug, picking the first free number exactly as the broker does. When the role is
    already a legal stem this returns None and the broker's own derivation stands.
    """
    stem = validate.slug_name(role, reserve=len("-99"))
    if stem == role:
        return None
    n = 1
    while store.get_agent(db, f"{stem}-{n}"):
        n += 1
    return f"{stem}-{n}"


# The only verbs refused while the store is degraded — see `store.schema_deficit`. All
# four create an agent, which is what writes the columns a degraded store does not have;
# everything else runs, because a live fleet has to be able to drain itself and a human has
# to be able to watch it do so. A deny-list, not an allow-list, on purpose: a verb added
# later defaults to *working*, and after a deadlock that cost seventeen agents, that is the
# direction to be wrong in.
_NEEDS_FRESH_SCHEMA = {"start", "delegate", "workspace", "restore"}


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
    # something has to ring it once it is free — until an events daemon exists, that
    # something is the next command anyone runs, which in a live session is constantly.
    # Never fatal: a doorbell that cannot ring must not take down `sb status`.
    try:
        b.flush_pending()
    except Exception as e:                       # noqa: BLE001 — best effort, always
        store.log_event(db, kind="flush_failed", error=str(e))

    try:
        return _dispatch(args, b, db, h)
    except HerdrError as e:
        print(f"sb: herdr [{e.code}] {e.message}", file=sys.stderr)
        return 1
    except sqlite3.OperationalError as e:
        # On a degraded store this is a command that turned out to need the new schema
        # after all — `_NEEDS_FRESH_SCHEMA` is a judgement, and this is what a wrong
        # judgement looks like from the caller's side. Say which, rather than leaking
        # "no such column: agents.branch" to an agent that cannot act on it.
        print(_degraded(deficit, args.cmd) if deficit else f"sb: store: {e}",
              file=sys.stderr)
        return 1
    except plugins_mod.PluginError as e:
        # Already logged, by the dispatch that raised it — one event per handler
        # invocation, not two for the ones that failed.
        return _plugin_failed(e)
    except (ValueError, KeyError) as e:
        print(f"sb: {_reason(e)}", file=sys.stderr)
        return 1


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
        def _confirm(existing: list[str]) -> bool:
            # Only ask when a human is actually there; scripts get the safe default.
            if args.json or not sys.stdin.isatty():
                return False
            print(f"already running: {', '.join(existing)}")
            return input("start another? [y/N] ").strip().lower().startswith("y")

        name = b.start(name=args.name, task=args.task, focus=args.focus,
                       new=args.new, board=args.board, confirm=_confirm)
        _emit(args, f"orchestrator '{name}' ready in its own workspace — switch to it, "
                    f"or: sb tell {name} \"...\"", {"name": name})
        return 0

    if cmd == "delegate":
        cleanup = "keep" if args.keep else ("close" if args.ephemeral else None)
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
                          name=args.name or _derived_name(db, args.role),
                          model=args.model, with_=args.with_,
                          cleanup=cleanup, me=me, **join)
        where = f" (joined workspace '{args.workspace}')" if args.workspace else ""
        _emit(args, f"delegated to {name}{where}",
              {"name": name, "workspace": join.get("workspace")})
        return 0

    if cmd == "ask":
        answers = b.ask(args.who, args.question, me=me, timeout=args.timeout)
        missing = [k for k, v in answers.items() if v is None]
        lines = [f"{k}: {v if v is not None else '(no answer — timed out)'}"
                 for k, v in answers.items()]
        _emit(args, "\n".join(lines), answers)
        return 1 if missing else 0

    if cmd == "tell":
        ids = b.tell(args.who, args.message, me=me, reply_to=args.reply_to)
        # Whether the doorbell actually rang. `tell` used to report plain success even
        # when the ring failed outright, so the sender proceeded believing the handoff had
        # happened — liveness loss, which in an async system is worse than an error.
        #
        # Still exit 0, and deliberately: the message is durable, and the next `sb`
        # command anyone runs re-rings it (see Broker.flush_pending). Being mid-turn is
        # the ordinary reason, not a failure. The report says who has not been told YET.
        waiting = sorted({m["to_agent"] for m in store.undelivered(db, exclude=(HUMAN,))
                          if m["id"] in set(ids)})
        note = f" ({', '.join(waiting)} mid-turn — will be rung when free)" if waiting else ""
        _emit(args, f"sent to {', '.join(args.who)}{note}",
              {"ids": ids, "undelivered": waiting})
        return 0

    if cmd == "inbox":
        if me == HUMAN:
            # A person has no mailbox — an agent that needs you blocks instead, and the
            # block is a row in `sb status --needs-me` until you answer it. Saying so
            # beats printing "(no new messages)", which reads as "nothing needs you" and
            # is a different claim entirely.
            _emit(args,
                  "you have no inbox — agents that need you BLOCK, and a block waits for "
                  "you in `sb status --needs-me` (answer with `sb tell <agent> \"...\"`)",
                  {"messages": [], "human": True})
            return 0
        msgs = b.inbox(me=me, peek=args.peek)
        if not msgs:
            _emit(args, "(no new messages)", {"messages": []})
            return 0
        lines = [f"[{m['id']}] from {m['from_agent']}: {m['body']}" for m in msgs]
        _emit(args, "\n".join(lines),
              {"messages": [dict(m) for m in msgs]})
        return 0

    if cmd == "done":
        b.done(args.summary, me=me)
        _emit(args, "done", {"agent": me})
        return 0

    if cmd == "block":
        b.block(args.why, me=me)
        _emit(args, "blocked — surfaced to the human, who will see it in "
                    "`sb status --needs-me` until they answer", {"agent": me})
        return 0

    if cmd == "status":
        # Straight to the module, like `output`: this reads the store and herdr side by
        # side and belongs to neither. The whole tree, not just the caller's children —
        # drift two levels down is still drift the caller is being lied to about.
        snap = status_mod.collect(db, h, live_only=args.live, needs_me=args.needs_me,
                                  mine=(me if args.mine else None))
        _emit(args, status_mod.render(snap), snap.as_dict())
        return 0

    if cmd == "presets":
        if args.name:
            try:
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
        # shown. Two rows read as empty for opposite reasons and must not look alike: a
        # tier with neither model nor effort is deferring to the CLI's own default (a
        # choice), while an unwired provider cannot be spawned at all. The second is legal
        # config — models.py keeps `provider` real ahead of its backend — so it is reported
        # per row rather than allowed to take the whole listing down, since finding out
        # WHICH tier is unspawnable is why anyone runs this.
        out: dict[str, dict] = {}
        lines = []
        for n, s in rows:
            try:
                flags, note = s.cli_args(), ""
            except models_mod.ModelConfigError as e:
                flags, note = [], f"UNAVAILABLE — {e}"
            out[n] = {"provider": s.provider, "model": s.model, "effort": s.effort,
                      "cli_args": flags, "error": note or None}
            lines.append(f"  {n:12}{s.provider:10}"
                         f"{note or ' '.join(flags) or '(provider default)'}")
        _emit(args, "\n".join(lines),
              {"default_provider": tiers.default_provider, "tiers": out})
        return 0

    if cmd == "cleanup":
        names = b.cleanup(args.name, include_kept=args.include_kept, force=args.force,
                          dry_run=args.dry_run, me=me)
        verb = "would close" if args.dry_run else "closed"
        _emit(args, f"{verb}: {', '.join(names) or '(nothing)'}", {"closed": names})
        return 0

    if cmd == "workspace":
        r = b.workspace_new(args.name, task=args.task, role=args.role, agent=args.agent,
                            base=args.base, focus=args.focus, board=args.board, me=me)
        _emit(args, "\n".join(f"  {k}: {v}" for k, v in r.items()), r)
        return 0

    if cmd == "restore":
        b.restore(args.name)
        _emit(args, f"restored {args.name}", {"name": args.name})
        return 0

    if cmd == "interrupt":
        b.interrupt(args.name, args.text)
        _emit(args, f"interrupted {args.name}", {"name": args.name})
        return 0

    if cmd == "inspect":
        # Straight to the module, like `status`: this reads the store and herdr side by
        # side and belongs to neither. It subsumes the old `sb output` — output.py is still
        # the reader underneath, it is just no longer a verb of its own, because "show me
        # the terminal" was never really the question anyone had.
        d = status_mod.inspect(db, h, args.name, lines=args.n, events=args.events)
        _emit(args, status_mod.render_detail(d), d.as_dict())
        return 0

    if cmd == "wait":
        r = status_mod.wait_for(db, h, args.name, until=args.until, timeout=args.timeout)
        _emit(args, r.render(), r.as_dict())
        # Non-zero so `sb wait w1 && ...` in a shell script means what it looks like.
        return 0 if r.ok else 1

    if cmd == "log":
        rows = store.recent_events(db, agent=args.agent, limit=args.n)[::-1]
        lines = [f"{r['id']:5} {r['agent'] or '-':16} {r['kind']:18} {(r['payload'] or '')[:80]}"
                 for r in rows] or ["(no events)"]
        _emit(args, "\n".join(lines), {"events": [dict(r) for r in rows]})
        return 0

    return 2


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
    the same treatment `sb ask human` gets.
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
