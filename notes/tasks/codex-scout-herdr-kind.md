# Scout task — does herdr itself support a non-Claude agent kind?

INVESTIGATION ONLY. Change no switchboard code.

Switchboard never talks to a pane directly: it shells out to the `herdr` binary
(`switchboard/herdr.py`), and spawns with `herdr agent start <name> --kind claude --pane
... -- <args>`. Whether codex can be driven at all hinges on what herdr's `--kind`
vocabulary is and how much of herdr's own machinery is Claude-shaped.

`herdr` is installed on this machine. Find out, from its `--help`, its docs/source if
reachable on disk, and by actually running it in a throwaway pane:

1. What values does `--kind` accept? Is `codex` among them? What does the kind actually
   change — the binary invoked, argument handling, status detection, session id capture?
2. How does herdr decide an agent is `idle` / `working` / `blocked` / `unknown`? Is that
   detection per-kind, or one Claude-specific scraper (switchboard's own comments say it
   matches Claude's spinner glyphs in the terminal title — check whether that is still
   true and whether a non-Claude kind gets something else).
3. `agent_session` / session id: where does herdr get an agent's session id from for each
   kind, and would it capture a codex thread id?
4. `herdr agent prompt` (paste into the chat box + Enter) and `send-keys esc`: are these
   kind-aware at all, or blind terminal writes? Does anything about them assume Claude's
   input box?
5. If `codex` is NOT a supported kind: what is the least-bad way to launch a codex TUI
   under herdr today (e.g. a generic/shell kind, or `--kind claude` with a different
   binary), and what breaks if you do — status, session id, restore?

Verify by actually starting a throwaway agent (in a scratch clone or scratch dir, NOT
against the live fleet store) rather than reasoning from help text. Tear down everything
you start; never an unscoped `pkill`. Do not spawn switchboard agents.

Deliverable: write findings to `notes/codex-scout-herdr-kind.md`. You own that file and
only that file. Mark every claim verified-by-running vs read-in-help. Commit on the
current branch, then `sb done` with a two-line summary — lead with the direct answer to
"can herdr run codex today, yes or no".
