# switchboard

switchboard runs a tree of AI coding agents across a set of terminal panes and gives them
one way to talk to each other: a command called `sb`. An agent delegates work, reports
back, or stops and asks a human — and everything it says leaves through that command, so
the coordination is something you can see, log and reason about rather than something
buried in a model's context.

## The problem

One agent working alone on a real repository runs out of room. The obvious fix is more
agents, and that is where it usually falls apart: two agents edit the same file, a child
finishes and nobody notices, an agent works out the answer to a question and writes it in
its own terminal where nothing is reading, or it quietly decides on your behalf something
you would have wanted to decide yourself.

None of those are model failures exactly. They are what happens when there is no protocol
— when "tell your parent" and "ask a human" are suggestions rather than the only channels
that exist. switchboard is that protocol, plus the plumbing to make it true.

## The shape of it

**Every agent lives in its own pane, beside a live view of the tree.** The panes, the
tabs and the git worktrees are managed by herdr, a terminal workspace manager for AI
coding agents; switchboard drives it and adds the coordination layer above.

**A human starts a dispatcher with `sb start`, and that is the only way one is
ever made.** A dispatcher is the top of a tree and holds no work of its own — it hands
what it is given to a lead, which owns that piece end to end and runs it through its own
children. Being a top is a stamp set at that moment, not something inferred later, and
`sb delegate` branches on it: a top's spawn gets a fresh workspace with a git worktree of
its own, anybody else's spawn gets a tab in the workspace the caller is already in. So
only the top ever creates a workspace, and a lead's whole subtree shares one checkout —
which is exactly why a lead has to hand its children disjoint files.

**Dispatchers and leads delegate rather than do.** The interesting agents in the tree
mostly spawn other agents, watch nothing, and wait. `sb delegate` returns immediately; the
parent ends its turn and is woken when a child reports. A parent that decides to do its
child's work itself is the failure mode this design is arranged against, and the prompts
say so in as many words.

**Nothing ever waits on anything.** There is no `ask`, no `wait`, no blocking call
between agents — they were tried and deleted. `sb tell` writes a message and rings a
doorbell, in one of three delivery modes:

- *next turn* (the default) — queued by the agent's own system and picked up at its next
  step. Cancels nothing.
- *when idle* — held until the target's turn actually ends. This is how a parent that has
  gone quiet learns a child finished, without polling.
- *interrupt* — cancels the turn in progress and delivers the instruction instead. For
  changing course, and nothing else.

A question is `sb tell --needs-reply`, which asks someone to answer at some point and
returns straight away.

**Work is reported upward as a summary, not a transcript.** `sb done` is how an agent
finishes: it commits, then writes one or two lines saying what it was asked, what it did,
and what that means. That summary is the entire thing its parent ever receives — no parent
reads a child's transcript, and an agent that answers in its own pane instead has, as far
as the system is concerned, said nothing at all. `done` does not close the agent; it is a
status change and a message, and the parent decides when to clean up.

**A human is reached exactly one way.** There is no human inbox — it existed once and was
removed, because messages nobody can see are worse than no messages. An agent that needs a
person writes the full question as the last message in its own chat and then calls
`sb block`, which ends its turn. The board lights up, the human reads that chat, answers
by typing into the pane, and the agent clears its own block and carries on.

That is the whole agent-facing vocabulary: `delegate`, `tell`, `inbox`, `done`, `block`,
`status`. The rest of `sb` — `cleanup`, `restore`, `inspect`, `log`, `board`, `workspace`,
`doctor` — is the human's. `sb board` is gated, not merely undocumented: it checks who is
calling and refuses an agent, because a screen made for a person is not a place an agent
should be reading its own state from.

## Why build this

Before building this, the landscape got a real look — a couple hundred multi-agent
orchestrators, Gas Town, Firstmate, AO, Claude Code's own Agent Teams. Most of what
switchboard prioritizes exists somewhere in that list, piece by piece.

What switchboard actually wants, together: several unrelated efforts running at once,
each its own tree and worktree, one command each, with no single orchestrator to funnel
through. An agent that is still an ordinary Claude Code session — no DSL, no graph to
declare — superpowered by default rather than assembled. Multi-agent procedures like
adversarial review written down as a single reusable file instead of re-explained by hand
each time. A Stop gate that mechanically refuses a turn nobody reported, not an advisory
rule. One honest channel to a human — a board and `sb block`, no inbox nobody reads.
Plugins that own a verb and durable state. All of it built on herdr rather than
reimplementing panes and worktrees.

Coverage exists in pieces: Firstmate has real typed human gates and lets a captain type
straight into any crewmate's pane; Agent Teams gives teammates persistent, addressable
identities. Nobody covers that whole set at once, which is the actual reason to build it.

It is also built for myself — my own workflow and thought process. For a personal tool
the question is not whether something similar exists, but whether anything existing fits
well enough to adopt instead.

## Architecture

About sixteen thousand lines of Python, standard library only — with one optional
exception. `tomllib` and `sqlite3` do the work a config parser and a database would
otherwise be pulled in for, and nothing switchboard *does* needs anything installed.

The exception is the board's appearance. `sb board` draws its panelled view with
[rich](https://pypi.org/project/rich/) when `rich` is importable and falls back to its
own plain ANSI renderer when it is not, so the tree, the clicks, the scrolling and every
word on the screen are the same either way — a missing dependency costs polish and
nothing else. There is no packaging file and nothing to install switchboard *as*:
`bin/sb` runs the checkout in place, under whatever `python3` is on PATH, so the way to
get the panelled board is `pip install -r requirements.txt` into that interpreter.

The modules meet at the store and not at each other:

- [`switchboard/store.py`](switchboard/store.py) — the single source of truth. Four SQLite
  tables (agents, messages, events, workspaces) under the repo's shared `.git`, so every
  worktree of the repo finds the same one. Operational state only, and disposable by
  construction.
- [`switchboard/broker.py`](switchboard/broker.py) — the agent-facing contract. One rule
  throughout: the agent states an intent and the tooling does the work. Correlation ids,
  retries, sequence numbers, pane ids and model names never surface.
- [`switchboard/herdr.py`](switchboard/herdr.py) — the only module that knows herdr
  exists. Everything above it speaks in agents and messages. It is also the insurance
  policy: if herdr goes away, this file is what gets replaced, not the system.
- [`switchboard/status.py`](switchboard/status.py) — the readouts. Joins three sources
  that each answer a slightly different question, and names the disagreement rather than
  picking a winner.
- [`switchboard/collector.py`](switchboard/collector.py),
  [`panel.py`](switchboard/panel.py), [`board.py`](switchboard/board.py),
  [`richboard.py`](switchboard/richboard.py) — one process collects the tree and
  publishes a snapshot; every pane's panel renders that file. Forty panes, one database
  handle. Two renderers, one contract: both hand back a line and its owner, so a click
  resolves the same way whichever drew the screen.
- [`switchboard/config.py`](switchboard/config.py) — everything shipped as default
  behaviour lives in `defaults/` as TOML and markdown: roles, model tiers, the
  agent protocol, every tunable number. A repo adds `.switchboard/` for its differences
  and only its differences.

A few of the shapes are there because of something that actually went wrong, and the code
says which:

- **The collector/renderer split.** A panel next to every agent used to mean every pane
  opening the database, and `store.connect()` is not read-only — it migrates schema, and
  in one path rebuilds the store outright. That was closed with a flag, but a flag is a
  fix somebody has to keep choosing on every future edit. Now every pane but the
  collector has no import that could reach a write, and a test checks that.
- **Turn edges as hooks.** Whether an agent is *working right now* was originally inferred
  from spinner glyphs in the terminal title. A cosmetic upstream change to those glyphs
  made every pane on the machine read as idle, which broke held delivery, made the
  reconciler interrupt agents mid-tool-call, and made the board lie. switchboard now
  records the fact itself at the two edges of a turn, via Claude Code's own hooks.
- **A Stop gate.** Agents finished turns without reporting, four times in one day, and
  their work stayed invisible. Ending a turn nobody reported is now refused mechanically
  rather than asked for politely.
- **Vocabulary is data.** Roles, presets, model tiers and prompts are files, not Python.
  No model name appears anywhere in the code; a role is a markdown file; adding a
  behaviour means adding a file and registering it nowhere.

There is a pytest suite in `tests/` — around 1,700 tests, no network and no herdr
required — covering the store's migration paths, the herdr adapter against a fake runner
whose cases were each verified against the live binary, and the structural rules above.
`python -m pytest tests` runs it, in parallel across every core (`pytest.ini` sets
`-n auto`; `-n0` for one process). It needs `requirements-dev.txt` installed.

## Design truth

[`DESIGN-TRUTH.md`](DESIGN-TRUTH.md) is the anchor of this repo and worth reading before
anything else. It holds only decisions confirmed by a human, each with the date it was
confirmed; agents working here may not add to it, infer entries into it, or contradict it.
Absence of an entry means undecided, not free.

It exists because the rest of the documentation in a repo like this is written by agents,
and an agent will happily build on top of another agent's guess. One file that is entirely
true and thin beats a fuller one that is partly invented — including this README, which is
downstream of it.

## Status

A working tool, used daily, and still moving. It is personal software: it assumes one
human, one machine, herdr on the PATH, and Claude Code as the agent. There is no packaging
story, no cross-platform testing, and the interesting surface — what agents are told at
spawn — changes as failures teach it something.

MIT licensed.
