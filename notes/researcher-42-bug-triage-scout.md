# Scout: bug-report triage terrain

Read-only recon for `bug-triage`. No files changed.

## 1. Report format

Storage: `/Users/andrew/.local/state/switchboard/plugins/report-bug/*.md` — one file per
report, filename `<STAMP>-<slug>.md` (e.g.
`2026-08-14-172112-sb-delegate-exits-1-with-task.md`), user-scoped (not per-repo). Source:
`switchboard/defaults/plugins/report-bug/__init__.py`.

`sb plugin report-bug list` prints `<id>  <what>` for every report on the machine, newest
first (data field returns id/path/what). `sb plugin report-bug show <id>` cats the file.
Confirmed 26 files on disk, matching the task's count.

Fields inside a report (markdown, `## heading` sections):
- title = the `what` one-liner, as an `# ` H1
- `## command` — exact command run (omitted if not given)
- `## expected` / `## actual` — free text (omitted if not given)
- `## context` — filed timestamp+tz, `by:` (agent name or `human`), sb version
  (`git describe`, includes worktree name), herdr version, python version+path, platform,
  `repo:` and `worktree:` paths
- `## session (last 20 lines)` — a bounded tail of the filing agent's Claude Code pane,
  captured via `sb inspect --json` subprocess; **absent** when a human filed it or the tail
  couldn't be read. Present on the mid/late-2026-08 reports I sampled, absent on the oldest
  ones and on the one human-filed report (`2026-08-08-020044-still-files`, which looks like
  a malformed/junk filing — no real command/expected/actual, `sb: not json at all`).

**No status/resolved marker of any kind.** There's no dedup, no index, no "closed" field —
by design (see the module docstring: "not designing dedup is the whole point... a bug filed
twice is evidence"). The only lifecycle verb is `drop <id>`, which deletes a report
outright, human-only. So triage state (still-broken vs fixed vs duplicate) has to live
somewhere else — nothing in the report format tracks it.

## 2. Issue-filing convention

`notes/issue-filing-commands.md` documents exactly one precedent: filing #40 and #41
(worktree-cleanup bug + a design question) on 2026-08-14. Pattern used:
- `gh issue create --label bug --title "..." --body-file <path-to-md-in-notes/>`
- Title style: plain-English sentence describing the failure, not a terse bug-tracker
  title (e.g. "Worktrees are never deleted: sb cleanup does not close the space,
  contradicting DESIGN-TRUTH")
- Body written as its own file under `notes/`, checked against code before filing
- Labels used so far: `bug`, `question` (repo has no `design`/`discussion` label)
- Related issues cross-linked with `gh issue comment` pointing at each other
- Filing was blocked by the permission classifier once (outward-facing action) and the
  agent stopped and asked a human rather than routing around it — worth remembering for
  whoever files the survivors here.

I did not find a DESIGN-TRUTH.md section specifically about bug reports or issue-filing
workflow — grepped for "bug report"/"report-bug" and got nothing.

## 3. GitHub state

Remote: `origin` → `https://github.com/Andrew3019/switchboard.git` (both fetch and push).

`gh issue list --limit 100 --state all` returns only **3 issues total, all OPEN, none
closed**:
- #41 — "Is one worktree per top-level delegate the right granularity?" (`question`)
- #40 — "Worktrees are never deleted: sb cleanup does not close the space, contradicting
  DESIGN-TRUTH" (`bug`)
- #38 — "Agents wedge on Claude Code's first-run auto-mode dialog: stuck/STALLED, and `sb
  tell --interrupt` cannot clear them" (`bug`)

**One clear duplicate**: #38 matches report
`2026-08-14-143944-agents-can-be-spawned-into-an` ("Agents can be spawned into an
interactive Claude Code first-run dialog and wedge there forever, unreachable by sb mail
and reported only as STALLED") — same failure, already filed as a GitHub issue. Whoever
triages that report should skip re-filing it and at most check whether #38 needs anything
added.

#40 and #41 don't correspond to any of the 26 report titles (worktree cleanup / granularity
isn't one of the filed bug reports) — they came from separate work, not from this report
backlog. So of the 26, only 1 is a known duplicate; the other 25 are plausibly still
unfiled.

## 4. Verification terrain — `switchboard/` source layout

16.8k total lines across the package. Rough map (line counts current as of `git log`
HEAD `fb04859`):

- **broker.py** (4657 lines) — the core: spawn, delegate, cleanup, block, tell/mail
  send-side, agent lifecycle (`Broker` class, `CleanupResult`, exceptions like
  `TaskUndelivered`, `Undeliverable`, `PaneUnusable`/`PaneNotReady`). Owns most of what the
  filed bugs are about (spawn/delegate reliability, cleanup gating).
- **status.py** (2054 lines) — board/status rendering: `collect()` builds a `Snapshot` from
  the sqlite events table, `_block_reasons`, `_undelivered_counts`, `display_rows`,
  `render`, the `clip()` truncation helper. Owns what `sb status`/`sb board` show.
- **store.py** (1786 lines) — the sqlite-backed event/agent store underlying status and
  broker.
- **cli.py** (1361 lines) — command parsing/dispatch for the `sb` CLI surface.
- **herdr.py** (1057 lines) — the herdr integration layer (pane control, the thing spawn
  and tell ultimately drive).
- **board.py** (960 lines) / **richboard.py** (716) — the interactive board UI.
- **plugins.py** (701) — plugin registration/dispatch (report-bug lives under
  `defaults/plugins/`).
- **collector.py** (589) — background collector that watches panes/state and writes
  events into the store (subject of one filed bug: "collector runs stale pre-fix code").
- **panel.py** (561), **config.py** (544), **presets.py** (353), **hooks.py** (397),
  **models.py** (252), **validate.py** (292), **output.py** (288), **roles.py** (114),
  **live.py** (155).

Recent churn (commits touching the file in the last 7 days): **broker.py 70**, cli.py 37,
status.py 28, store.py 23, herdr.py 17, board.py 15, collector.py 10, hooks.py 4, panel.py
2. Broker and cli are by far the hottest files — consistent with most of the 26 reports
being about spawn/delegate/cleanup/mail behavior, which live there. That also means a
report against broker.py logic filed even a few days ago has decent odds of having been
overtaken by a fix since — worth checking git log on the specific function before assuming
still-broken.

## 5. Verification difficulty — 3 sampled reports

- **`2026-08-09-071134-sb-cleanup-silently-refuses-to-close-a...`** ("cleanup prints
  'closed: (nothing)' with no reason") — **(a) obvious from code, and it looks fixed.**
  `broker.py:419` has a `CleanupResult` class whose docstring literally says: "It exists
  because `closed: (nothing)` is not a report... `CleanupResult.refused`... A gate firing
  in silence is the bug this closes: `closed: (nothing)` told you the outcome and never the
  rule." That's the bug being described, already addressed in code. Very likely stale/fixed
  — a live run would just be confirmation, not discovery.

- **`2026-08-09-002336-sb-status-truncates-a-blocked-agent-s...`** ("sb status truncates a
  blocked agent's reason to ~60 chars") — **(a) leans obvious, but has a wrinkle.**
  `status.py:1754` does `why[:70]` in the compact "attention" summary line — matches the
  complaint almost exactly (70 vs the reported ~60). But `status.py:1988`, in the detail
  view (`sb inspect`/similar), prints the full `a.blocked_why` untruncated. So the question
  isn't "is it truncated" (yes, provably, by reading the code) but "is that a bug or
  intended" — the summary line is meant to be compact and full detail exists one level
  down. Reading code answers the mechanics; whether it counts as the *bug* as filed needs a
  judgment call, not a live run.

- **`2026-08-14-172112-sb-delegate-exits-1-with-task_undelivered...`** ("delegate exits 1
  with task_undelivered even though the task did arrive; on another agent the text sat
  unsubmitted, duplicated by 3 retries") — **(b) needs a live run.** This is a race/timing
  bug in how `sb delegate` submits text into a herdr pane and confirms delivery
  (`TaskUndelivered` in broker.py, `_own_sb_bin`/pane-readiness helpers). It's inherently
  about real subprocess/pane timing, not a static logic error visible by inspection —
  `broker.py` churned 70 times in 7 days so this exact path may have moved. Confirming
  "still broken" needs delegating in an isolated clone and watching for the failure mode,
  same as the task instructions' own verification protocol calls for.

**Overall read on the mix**: several of the 26 (especially the older, terse ones with no
session tail, and ones describing a bug whose fix is now visibly in the code / whose
docstring name-checks the bug) look like they can be triaged by code-reading alone.
Anything touching live spawn/delegate/mail timing, pane state, or herdr integration
(broker.py, herdr.py) is going to need an actual isolated-clone run to be sure — code
reading can rule a report *in* (bug still visibly present) faster than it can rule one
*out* (absence of visible bug isn't proof the race doesn't reproduce).
