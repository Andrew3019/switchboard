# herdr outage, 2026-08-16 ~10:14:52–10:14:57Z (03:14:52–03:14:57 local) — root cause

Read-only forensics. Sources used: `~/.config/herdr/herdr-server.log` and
`herdr-client.log`, switchboard's `state.db` (read-only URI), Claude Code
transcripts under `~/.claude/projects/`, `notes/tasks/codex-probe-identity-and-turn.md`
on the `codex-support` worktree, shell history, and the three prior-branch scout
notes named in the task. No state-changing command was run anywhere.

## 1. What killed herdr — strongest supported explanation

**`herdr workspace close w1H6`, issued by the researcher agent `probe-identity`
(grandchild of `codex`, child of `codex-support`), is the event that immediately
precedes — and is inseparable in time from — the fleet-wide outage.**

Timeline, all from `herdr-server.log` (times UTC = local+7h):

- `10:14:46.68`(client-side, from `probe-identity`'s own transcript) — it issues
  `herdr workspace close w1H6` as the last step of its probe, tearing down the
  scratch workspace it had been using to spin up throwaway `codex`-kind agents
  for hook/notify experiments (per its task, `notes/tasks/codex-probe-identity-and-turn.md`).
- `10:14:48.284774Z` — server receives the request (`request_id="cli:workspace:close"`)
  and closes it: `workspace closed ... outcome="ok" workspace_id="w1H6"`.
- `10:14:48.297918Z`–`10:14:52.829706Z` (**~4.5s**) — the server log shows **over 20
  panes dying in sequence, across the entire fleet, not just w1H6's own two panes**
  (pane ids 3518, 3513, 3461, 3279, 3511, 3401, 3439, 3515, 3491, 3517, 3512, 262,
  3450, 3488, 3490, 3429, 3388, 3489, 3516, 3514, 3389 — spanning many unrelated
  workspaces/agents). Exit signals are mixed: mostly `Hangup`, several `Terminate`,
  several `Kill`. The two panes belonging to w1H6 itself (3518, 3513) each produce a
  `WARN herdr::app::actions: PaneDied for unknown pane` immediately after the close —
  i.e. herdr's own bookkeeping had already treated them as gone by the time the
  async child-exit reaper fired for them, a race between the explicit close and
  normal process-exit handling.
- `10:14:52.829706Z` — the last log line before a total gap: an `agent.list` API
  request completes with `outcome="error"`.
- `10:14:52.832971Z` (`herdr-client.log`) — the **client** (pid 5696) logs a *clean*
  shutdown, `app.shutdown outcome="completed"` — this is the line the prior "live"
  scout found and read as "restarted cleanly, no crash." It is real, but it lands
  in the same second as the tail end of the server-side pane-death cascade above,
  not in isolation.
- **Silence** in the server log from `10:14:52.83` to `10:14:56.948` (~4.1s) — no
  panic, fatal, or signal line anywhere in that gap or before it.
- `10:14:56.948Z` — a **new** server process appears (raises its fd soft limit,
  opens a fresh `herdr.sock`) and respawns all 21 panes from the last persisted
  `session.json` (`persist.restore outcome="ok" workspaces=12`).
- `10:14:57.363Z` — a new client (pid 28286) starts and reconnects.

`probe-identity`'s own Claude Code transcript
(`~/.claude/projects/-Users-andrew--herdr-worktrees-switchboard-codex-support/ea8ef05e-0930-4f88-af22-50f597a0c067.jsonl`,
mtime `03:14`) **ends exactly at the `workspace close` tool result** — no further
turns. That is consistent with `probe-identity`'s own pane (itself a herdr-hosted
pane, in the `codex-support` workspace, on the very same shared server) being one
of the ~20 panes killed in this cascade: its process died with everyone else's.

**What this proves:** the timing correlation. Across ~24 hours of server log this
is the only workspace/agent-lifecycle call that immediately precedes a full-fleet
pane teardown and server restart; nothing else in any agent's transcript or in the
shell history comes close in timing. herdr is a **single shared daemon for the
whole machine** (`~/.config/herdr/herdr.sock`, `-server.log`, `-client.log` are all
global, not per-repo/per-workspace) — so a "scratch workspace" as instructed in
`probe-identity`'s task was never actually isolated from the live fleet; there is
no such isolation mechanism in herdr today.

**What this does NOT prove:** the internal mechanism. No panic/fatal/signal string
appears anywhere in the log, no macOS crash report exists for `herdr` in
`~/Library/Logs/DiagnosticReports/` (checked, empty besides an unrelated stale
`Retired` folder), and I did not have herdr's source available to read. So I
cannot show *why* closing w1H6 (which at that moment held two just-used `codex`
CLI subprocesses from the notify/hook probe) took the whole server down — only
that it did, within under 5 seconds, every time this incident is examined. Two
live candidates for the mechanism, neither confirmed:
  - a race in herdr's pane-exit reaping (suggested by the `PaneDied for unknown
    pane` warnings) that corrupted shared server state and brought the whole
    process down;
  - the close tearing down a `codex` subprocess that was itself in an unexpected
    state (the probe had just sent it `esc`/`C-c`/`C-c` to interrupt a running
    `codex exec`, then started a *fresh* codex agent in the same pane seconds
    before closing the workspace) and something in reaping *that* process group
    cascaded outward.

**What would settle it:** herdr's own source (not vendored in this repo) around
its pane-reap / workspace-close code path, or a way to reproduce this exact
sequence (spin up a `--kind codex` pane, interrupt it, start a fresh one, close
the workspace) in isolation with the real herdr binary and watch whether it
crashes the daemon. I did not attempt that reproduction — it would touch the live
daemon and is out of scope for read-only forensics.

## 2. Was `codex` involved?

**Not directly, but yes at the tree level — stated plainly:**

- The root dispatcher `codex` itself did nothing during the outage. Its transcript
  (`~/.claude/projects/-Users-andrew-Code-switchboard/3371cf0b-a9cd-43b4-8c35-2d2ae0cfb98c.jsonl`)
  shows its last activity before the crash was delegating `codex-support` the
  previous evening at `2026-08-15T22:24Z`; its next activity is Andrew telling it
  "herdr crashed, i was able to restore u" at `10:35:11Z` the next morning — over
  12 hours of silence spanning the crash. Everything it did after that (`sb list`,
  `sb status`, `sb restore codex-support`, `sb tell`) is read-only or a documented,
  sanctioned recovery action, not a cause.
- Its child `codex-support` (the lead) was also completely idle during the crash
  window: its transcript shows its last action was dispatching the third probe
  round at `22:51:39Z` the previous evening, then nothing until it was woken by
  mail at `10:36:00Z` post-restart.
- The agent that **was** live and issuing commands at the exact moment of the
  crash is `probe-identity` — a researcher two levels down from `codex`
  (`codex` → `codex-support` → `probe-identity`), doing exactly the kind of work
  `codex`'s tree exists to do here: testing the real `codex` CLI tool's behavior
  inside herdr panes, per `notes/tasks/codex-probe-identity-and-turn.md` (spin up
  throwaway `--kind codex` agents, send them interrupts, start fresh ones, tear
  the workspace down). Its `session_id` was never recorded in switchboard's store
  (it never reached a point where herdr reported one back — this is also why the
  prior restore-list scout excluded it as "no session id, nothing to restore"),
  but its Claude Code transcript exists on disk and is unambiguous about what it
  ran and when.
- `wording` (the other no-session-id dispatcher named in the task) is unrelated:
  created `03:08:07Z`, only one event ever recorded (`start`), and no Claude Code
  transcript exists for it anywhere under `~/.claude/projects/` — it never got far
  enough to run anything before the crash hit.

So: **no**, `codex` and `codex-support` did not do anything themselves at the time
of the crash. **Yes**, in that a `codex`-tree agent — `probe-identity`, doing the
codex-CLI probing that `codex` was dispatched to investigate — ran the one command
that immediately precedes the outage in every log examined.

## 3. What would prevent a recurrence (reported, not implemented)

- **Give herdr real isolation for "scratch" work**, or document clearly that none
  exists. Today `CODEX_HOME`/scratch directories isolate the *tested* CLI's config,
  but the herdr daemon itself, its socket, and every pane on the machine are one
  shared process — closing a "scratch" workspace is not sandboxed from the live
  fleet at all. If herdr can't offer a second, disposable daemon instance for this
  kind of test, task instructions that say "use a scratch workspace" for
  experiments that spawn/interrupt/kill real agent CLI subprocesses are making a
  safety promise herdr can't keep.
- **Treat `herdr workspace close` on a workspace with a just-interrupted or
  freshly-started agent subprocess as a known-risky operation** until the
  mechanism above is understood — e.g. avoid closing a workspace within seconds of
  sending it an interrupt sequence (`esc`/`C-c`) and immediately starting a new
  agent in the same pane, which is the exact sequence `probe-identity` ran right
  before the close.
- **Get herdr's own source alongside this repo** (or file the crash upstream) so
  the pane-reap/workspace-close path can actually be read, rather than inferred
  from timing alone — right now nobody investigating an outage like this can go
  past "these two things happened within 5 seconds of each other."
- **Make the outage itself detectable without inference**: neither herdr's
  structured log nor macOS's crash reporter recorded anything for this event
  beyond a silent gap. A supervisor that notices "server socket unreachable" and
  writes one line with a wall-clock timestamp (even without a cause) would have
  turned this whole investigation from log archaeology into a two-line lookup.

## What's proven vs. inferred (summary)

**Proven** (read directly from logs/transcripts): the exact command
`probe-identity` ran and when; that it was the last thing anyone did before the
outage; that the server-side pane-death cascade and client shutdown both land in
the same ~5-second window immediately after that command's server-side effect;
that `codex` and `codex-support` were idle throughout; that `wording` never ran
anything; that no panic/crash-report evidence exists anywhere checked.

**Inferred, not proven**: that the workspace-close call *caused* the crash rather
than being an unrelated coincidence in the same few seconds, and any specific
internal mechanism for how it might have done so.
