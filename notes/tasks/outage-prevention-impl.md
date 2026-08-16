# Task: stop the outage happening again

An investigation established what took herdr down on 2026-08-16. Read
`notes/herdr-close-mechanism.md` and `notes/herdr-outage-cause.md` in this
worktree first — both are committed here. Do not redo that work.

The short version: `herdr workspace close` on a repo's *primary* checkout silently
closes every other open workspace that is a linked git-worktree of the same repo —
they share one internal grouping key. An agent ran that command by hand on a
scratch workspace, because its own task told it to, and took the whole fleet down.
No normal `sb` verb can trigger it; switchboard only ever closes panes one at a
time. Five of the fleet's currently-open workspaces sit in exactly that dangerous
group today.

## Scope — yours and nobody else's

You own `acceptance/accept.py`, agent-facing guidance text, and new files under
`notes/`. Another agent is working in this same worktree on
`switchboard/broker.py`, `switchboard/cli.py` and `tests/test_broker.py` — do not
touch those, and do not touch `switchboard/output.py` either (a third change is
queued there).

**`DESIGN-TRUTH.md` is Andrew's alone — do not edit it.** If you conclude a change
belongs there, say so in your summary and leave it.

## Three things to do

1. **Harden `acceptance/accept.py`'s test-clone teardown.** It is the one place in
   the repo that calls herdr's workspace-close API. It is contained but not
   provably safe: if it were ever pointed at a primary checkout rather than a
   throwaway clone, it would do exactly what happened here. Add the path check the
   mechanism note describes, so it refuses to close anything that is not the
   scratch clone it created. Small and defensive — do not restructure the file.
2. **Stop agents being told to run raw `herdr workspace close`.** The agent that
   caused this was following its instructions. Find where teardown guidance is
   given to agents — task templates, presets under `.switchboard/presets/`,
   whatever the repo actually uses (check, do not assume; every document here
   except `DESIGN-TRUTH.md` is untrusted until checked against the code) — and make
   the rule explicit: tear down with `sb`, never with raw `herdr workspace close`,
   and say in one clause why. If the right home for that rule turns out to be
   `DESIGN-TRUTH.md`, report it instead of editing it.
3. **Write the upstream bug report as a note**, at
   `notes/herdr-workspace-close-upstream-bug.md`: what herdr does, the grouping key
   that causes it, how to reproduce it in principle, and why it is severe (one
   machine-global daemon, no isolation between a scratch workspace and a live
   fleet). herdr's source is at `/Users/andrew/Code/herdr` — read it to get the
   report right. **Do not file it, do not open an issue, do not commit anything to
   that repo, do not modify it.** Andrew decides whether and where it gets filed.

## Rules

- Never run `herdr workspace close` yourself, on anything, for any reason.
- Do not run state-changing `sb` commands against the live fleet, and never an
  unscoped `pkill`.
- Verify your `accept.py` change actually runs: at minimum exercise the guard both
  ways (a path it should accept, a path it must refuse). One or two tests, in the
  style the repo already uses. Run the suite with
  `/Users/andrew/anaconda3/bin/python -m pytest tests`.

## Deliver

Commit on branch `herdr-outage-prevention`. Do not push, do not open a PR, do not
merge — your parent integrates. In your `sb done` summary: what you changed, what
you verified, and anything left unproven.
