# Task: why does closing one herdr workspace take the whole daemon down — and can switchboard trigger it itself?

A sibling investigation established the root cause of the 2026-08-16 outage: an
agent ran `herdr workspace close w1H6` on a scratch workspace, and within ~4.5
seconds every pane on the machine-wide herdr daemon died and the server restarted.
Read `notes/herdr-outage-cause.md` in this worktree first — it has the full
timeline and log lines. Do not redo that work.

What it could **not** settle is the mechanism, and the mechanism is what decides
the prevention. That is your job.

## Rules

Read-only. Do **not** run `herdr workspace close`, or anything else that could
touch the live daemon's workspaces or panes — herdr is a single machine-global
daemon, so there is no safe place to reproduce this, and doing it would take
Andrew's live fleet down a second time. If you conclude a live reproduction is the
only way to settle it, say so in your notes and stop; do not attempt it. Run no
state-changing `sb` command. Query switchboard's store only through
`file:/Users/andrew/Code/switchboard/.git/agentflow/state.db?mode=ro`.

Your only writes are to `notes/herdr-close-mechanism.md` in this worktree,
committed on branch `herdr-outage-prevention`. Other agents are working in the same
worktree on other files — touch nothing else.

## Questions, in priority order

1. **Can switchboard itself trigger this?** Search `switchboard/` for every path
   that calls herdr's workspace-close (or anything close-adjacent) — `sb cleanup`,
   workspace retirement, worktree teardown, agent close-by-identity. Cite
   file:line. If any normal `sb` operation issues that call, then the fleet can
   kill itself during ordinary use and this is not a one-off caused by one
   careless agent. **This is the most important question — answer it first and
   answer it plainly.**
2. **What is the mechanism?** Find herdr's source or binary on this machine
   (`which herdr`, `~/.local/bin/herdr`, any checkout, any cargo registry copy,
   symbols in the binary). If source is reachable, find what closing a workspace
   does to panes that do not belong to it — the outage log shows mixed `Hangup`,
   `Terminate` and `Kill` exits across ~20 unrelated panes, plus two `PaneDied for
   unknown pane` warnings suggesting a race between the explicit close and the
   child-exit reaper. If source is not reachable, say so and stop guessing.
3. **Is it the close specifically, or the workspace?** `w1H6` was a scratch
   workspace hosting throwaway agents of a different provider kind (`codex`). Weigh
   whether the trigger was closing a workspace at all, closing one with live panes,
   or something about those particular child processes. Check the server log for
   earlier, survived workspace closes — if closes normally succeed, what was
   different this time is the finding.
4. **Prevention.** Given the answers above, what change actually prevents a
   recurrence? Separate what switchboard can do on its own (guardrails, refusing a
   close, never issuing one, warning an agent off) from what needs a fix in herdr
   itself. Be concrete about the switchboard-side change: file, function, what
   changes.

## Deliver

`notes/herdr-close-mechanism.md`: answer to each of the four, marking proved
versus inferred, and ending with a single recommended prevention plus what it
costs if you are wrong. Do not implement anything.

Every document in this repo except `DESIGN-TRUTH.md` is untrusted until checked
against the code.
