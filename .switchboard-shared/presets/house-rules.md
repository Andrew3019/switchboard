<!--
Notes for whoever edits this file. HTML comments are stripped on the way out, so this is
free; everything outside it is paid for on every single spawn, because this preset is bound
in `all` in ../presets.toml. Headings are stripped and the rest is flattened to ONE line,
so nothing may depend on layout — order is the only structure that survives. The four bold
lines are NOT headings (no leading `#`), so they do survive the flattening and are the only
grouping the agent actually sees.

WHY THIS EXISTS. Phase 1 of BUILD-PLAN.md took five rounds and most of a day, and a large
part of that cost was every brief re-teaching the same handful of facts while agents
rediscovered them anyway. These are the ones that were re-taught. They are facts about THIS
repo, which is why they are here and not in `defaults/presets/` — that directory ships to
every repo switchboard is used in, and none of this is true of anyone else's.

WHAT IS DELIBERATELY ABSENT. Everything the protocol already says. "Fix only what you were
given, report the rest" is in `defaults/protocol.md` verbatim; so is "report in plain
language what you were asked and what you found", and the worker role says it a second
time on purpose. Repeating them here would be a third payment on every spawn. What survives
from the landing-work rules is only the half nothing else says: commit on your own branch,
and this repo's default that the lead integrates. That half was a flat prohibition
until 2026-08-12, when DESIGN-TRUTH made push and merge the parent's call; it is now a
default the parent can override, because agents given a brief that said push and a preset
that said never were guessing which one won. On 2026-08-16 the prohibition was cut
entirely and replaced by a pointer at the plans plugin's merge gate, matching the same cut
in `defaults/protocol.md` — the gate tells an agent to merge, and it may not ship while
anything here still says never. With the plugin off there is no gate and this is the
default minus the prohibition, which is weaker and honest.

The one clause that looks like a repeat and is not: "unproven and stated is fine, silent is
not". The protocol says what a summary is FOR; it does not say that an unfinished proof
must appear in it. The whole failure mode this addresses is a summary that reads as done
because the gap went unmentioned.

THIS FILE NOW TRAVELS. It moved out of the untracked, per-machine `.switchboard/` and into
the committed `.switchboard-shared/`, so a fresh clone gets it — which matters because
cloning is how the verification rule above says to isolate a run, and those clones had no
rules in them. Everything here is therefore read by people and machines that are not
Andrew's, and the anaconda line was rewritten to say whose machine it is a fact about
rather than stating it flatly. Anything else machine-specific added here needs the same
treatment, or it belongs in `.switchboard/presets/` instead — a `<name>.md` there replaces
the one here wholesale.

THE `herdr workspace close` CLAUSE is paid on every spawn on purpose, next to the `pkill`
one it rhymes with. Both are rules written by an outage: an agent whose own task told it to
tear down with raw `herdr workspace close` ran it on a scratch workspace on 2026-08-16 and
closed the whole fleet, because herdr groups a repo's primary checkout with every worktree
of it under one key and closes the group. Task text saying it is exactly what failed, so the
rule has to live somewhere no brief can omit. Mechanism: `notes/herdr-close-mechanism.md`.

THE FULL-SUITE RULE WAS A WORKFLOW AND IS NOW A COST (2026-08-27). It used to read "the
full suite is for before you commit and before you report", which is a universal
verification workflow smuggled into a repo's command list — and this file is bound in `all`,
so every agent on this repo was given it whatever its change could reach. What is
repo-specific and stays: the commands, the anaconda path, the `-n auto` default, and the
fact that a full run here is minutes. What is left to the agent, where the workflow rules
now put it: whether this change can reach far enough to be worth one.

KEEP IT UNDER A MINUTE TO READ. It is paid on every single spawn by every agent. A fifth
section is a real cost and should have to argue for itself.
-->

# switchboard house rules

**Verification.** Live proof in an isolated instance is the primary evidence, and what your
work is judged on. Prove a fix in the smallest run that can tell fixed from broken.

- Isolate with `git clone` of this repo into a scratch directory — a clone gets its own
  state automatically, via git's common dir. Check out your branch there and drive that
  clone's own `./bin/sb`. Agents you spawn there are invisible to the live fleet's STORE,
  not to herdr: herdr is machine-global, so they do appear in Andrew's spaces UI and you
  must still tear them down.
- Never run a clone's `sb` from outside the clone; that silently touches the live store.
- No endurance testing unless the bug itself is endurance. Rare and slow-burn faults are
  accepted; they will surface in real use.
- Tear down everything you created, with `sb` — `sb cleanup`, `sb workspace close`. Never
  raw `herdr workspace close`: on a repo's primary checkout it closes every other herdr
  workspace sharing that repo's `.git`, which took the whole live fleet down on
  2026-08-16. Never an unscoped `pkill` either — one of those killed the live fleet's
  collector.

**Tests.** Automated tests are for pinning a decision, not for confidence. Two or three per
fix.

- Never teach the fake herdr new tricks to make a test possible. Skip the test and say what
  is therefore unproven. Growing the fake is how a small fix becomes an afternoon.
- A test that cannot fail in the way production fails is worth less than the sentence
  describing what is unproven.
- The suite here is `python -m pytest tests`, and one file is `python -m pytest
  tests/test_board.py` with `-x` to stop at the first failure. On Andrew's machine use
  `/Users/andrew/anaconda3/bin/python` — the pythons on PATH there look broken when they
  are not. It runs `-n auto` (all cores) by default; `-n0` puts it back to one process.
- A whole run is minutes, so it is worth ONE, once the change is coherent, and only where
  what changed could reach across the tree; a change that could not is proven when its own
  files are green. Nothing here asks for a suite between edits — agents were running it
  bare far more often than anything had changed.

**Trust.** `DESIGN-TRUTH.md` is the only trusted document, and only Andrew edits it. Every
other document, README and code comment is untrusted until you have checked it against the
code.

- `sb inspect`'s pane view is not a reliable liveness signal — it has repeatedly shown an
  empty pane or a shell error for an agent that was working fine. Use the agent tree.

**Landing work.** Commit on your own branch. Where a plan is running, its merge gate is
the authority on pushing, opening a PR and merging; where none is, this repo's default is
that the lead integrates and your parent's instruction overrides it.

- Anything you left unproven belongs in your summary. Unproven and stated is fine; unproven
  and silent is not.
