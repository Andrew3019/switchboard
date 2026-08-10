# Audit part C — panes, focus and the board split

Auditor: `reviewer-3`. Read-only; nothing under `switchboard/` was changed.

**What was audited:** the checkout I was given —
`/Users/andrew/.herdr/worktrees/switchboard/worker-2`, branch `worker-2`, HEAD `3b58c53`.
All `file:line` references below are that tree unless they say "main".

**Read this caveat first.** The `sb` on PATH is *not* this tree. `readlink -f $(which sb)`
→ `/Users/andrew/Code/switchboard/bin/sb`, i.e. local `main` at `713a1f4`. `main` carries
three commits `worker-2` does not have (`git merge-base --is-ancestor HEAD main` → false):

```
713a1f4 Give every agent a board pane, sized right, and take it down with them
d38425f Close an agent's board with the agent, so no empty tab is left behind
e8e5c70 Give every agent a board beside it, and make the board the small pane
```

Those commits already fix the largest finding below. So the verdicts are: **BROKEN /
PARTIAL on the branch under review, with the board half largely already fixed on main and
not yet merged into `worker-2`.** Where main differs I say so explicitly.

---

## Entry 1 — "Every single view I see that is made by sb … needs to be a split pane with `sb board`" (+ `--no-board` is rejected)

### Verdict: **BROKEN** (on `worker-2`). On `main`: **PARTIAL**.

### Evidence — `worker-2`

**a. `_open_board` has exactly three call sites, and none of them is `delegate`.**

```
$ grep -rn "_open_board\|open_beside" switchboard/
switchboard/broker.py:468      _top  (sb start, existing agent)
switchboard/broker.py:492      _top  (sb start, new agent)
switchboard/broker.py:644      workspace_new
switchboard/broker.py:524      def _open_board
```

`delegate` is `switchboard/broker.py:1261-1380`. It resolves a pane at `broker.py:1338`
(`pane = pane or self._tab_for(wsid, where)`), starts the agent at `:1361`, and returns at
`:1379` having never mentioned the board. **Every agent an orchestrator spawns therefore
lands in a bare pane.** `delegate` is the single spawn path for everything except the top
orchestrator and a workspace lead, so this is the common case, not an edge.

**b. A board beside the parent is not visible in a child's tab.** `delegate` places
children with `create_tab` (`switchboard/herdr.py:256`), which is documented there as
explicitly *not* a pane split. The board is a pane split (`board.open_beside` →
`herdr.split_pane`, `switchboard/board.py:396`). Panes belong to tabs — confirmed against
the live herdr, where every row of `herdr pane list` carries a `tab_id` and each `tab_id`
groups its own panes. So the top orchestrator's board pane covers the top orchestrator's
tab only.

**c. `workspace_new` gates the board on the lead's role.**

`switchboard/broker.py:639`: `if board and role == MAIN:`

`MAIN` is `vocabulary.main_role` = `"orchestrator"` (`defaults/settings.toml:80`). The
default `--role` for `sb workspace new` is `WORKSPACE_ROLE` = `"orchestrator"`
(`defaults/settings.toml:95`), so the default path does open one — but
`sb workspace new X --role worker` opens a lead in a workspace with no board. The
docstring at `broker.py:604-607` states this is deliberate ("a worker forked into its own
worktree runs nobody, so a panel there would be an empty view"). That reasoning is
contradicted by the entry, and `main` has since reversed it (`main` broker.py:689-692).

**d. `restore` never opens a board — true on `worker-2` *and* on `main`.**
`switchboard/broker.py:1800-1852` makes a fresh tab at `:1826` and returns at `:1852` with
no board call. `sb restore <name>` (`switchboard/cli.py:849-852`) therefore always yields
a bare pane. Checked on main too: `sed -n '1905,1975p'` of main's `broker.py` contains no
`_open_board`.

**e. `--no-board` still exists — on both branches.** It is on the explicitly-rejected list.

```
$ ./bin/sb start --help
usage: sb start [-h] [--json] [--name NAME] [--no-focus] [--no-board] [task]
  --no-board   do not open the clickable board beside it

$ ./bin/sb workspace new --help
  --no-board   do not open the clickable board beside the lead
```

Source: `switchboard/cli.py:113` (`sb start`), `switchboard/cli.py:256`
(`sb workspace new`), plumbed at `cli.py:681-682` and `cli.py:846`, received as
`board: bool = True` at `broker.py:397`, `:435`, `:589`. Present unchanged on main
(`main` cli.py:113, :256).

**f. Two silent no-board paths inside `_open_board` itself.**
- `broker.py:538-539` — an empty pane id returns with no board and no log line.
- `broker.py:544-552` — a bare `except Exception: return` around the meta/`pane_ids()`
  lookup. If herdr cannot be asked what is open, no board opens and nothing is recorded.
  main added a log line for the herdr-refusal case (`main` broker.py:582-587); this
  swallow is still there on both.

**g. Nothing takes the board pane away on `worker-2`.** There is no `_close_board`
(`grep -n "_close_board" switchboard/broker.py` → nothing; only three raw `close_pane`
calls at `:928`, `:1738`, `:1839`). main added one (`main` broker.py:589). Not an entry
violation on its own, but it is why "board on every agent" needs the teardown half.

### What main already fixes, verified live

main's `delegate` calls `self._open_board(name, agent.pane_id or pane, cwd=str(where))` at
`main` broker.py:1483, and `workspace_new`'s role gate is gone. Confirmed against the
running session rather than read: every delegated tab in workspace `w1E` has
`pane_count: 2` (`herdr tab list`), and the second pane is the board —

```
$ herdr pane process-info --pane w1E:pS
… "argv":["…/Python","-m","switchboard.board"] …
$ herdr pane read w1E:pS --lines 20 --format text
click a row to focus it · scroll to p
```

Still open on main: `--no-board` on two verbs, and a boardless `restore`.

### Gaps (one line each, buildable)

1. `switchboard/broker.py:1379` — `delegate` opens no board; port main's `_open_board(name, agent.pane_id or pane, cwd=str(where))` (main broker.py:1483) in before `self.h.prompt`.
2. `switchboard/broker.py:639` — drop the `and role == MAIN` gate so a non-orchestrator workspace lead also gets a board.
3. `switchboard/broker.py:1800` / `switchboard/cli.py:849` — `restore` puts an agent in a fresh tab with no board; open one there (still true on main).
4. `switchboard/cli.py:113` and `switchboard/cli.py:256` — remove `--no-board`, and the `board: bool` params it feeds at `broker.py:397`, `:435`, `:589`.
5. `switchboard/broker.py:544-552` — a herdr failure means no board and no event; log it, as main does at `main` broker.py:582-587.
6. `switchboard/broker.py` — no `_close_board`; once every agent has a board, cleanup must take the board pane with the agent or leave an empty tab per close (main broker.py:589).

---

## Entry 2 — "`sb start` focuses the pane. Nothing else ever focuses on spawn." (+ "focus as a flag" is rejected)

### Verdict: **PARTIAL** — the behaviour is right by default; the rejected flag is still on the CLI.

### Evidence

**a. `sb start` does focus.** `broker.start` takes `focus: bool = True`
(`switchboard/broker.py:397`) and `_top` calls `self._focus(name, focus)` on both the
existing-agent branch (`:469`) and the new-agent branch (`:493`). `_focus`
(`broker.py:570-576`) calls `self.h.focus(name)` → `herdr agent focus <name>`
(`switchboard/herdr.py:503-505`). This half is satisfied.

**b. There are only two focus call sites in the whole package.**

```
$ grep -rn "\.focus(\|agent\", \"focus" switchboard/*.py
switchboard/broker.py:574        self.h.focus(name)          # _focus
switchboard/board.py:367         herdr agent focus <name>    # the click
```

`board.focus` (`switchboard/board.py:364-375`) is reached only from the click handler
(`board.py:520`). That is navigation, which the entry explicitly permits.

**c. No spawn-adjacent herdr call asks for focus.** Every topology call passes
`--no-focus` explicitly: `create_tab` (`herdr.py:267`), `create_workspace` (`:290`),
`split_pane` (`:308`), `worktree create` (`:340`), `worktree open` (`:359`). So
`delegate`, the fork, and the board split itself do not steal focus. `delegate`
(`broker.py:1261-1380`) contains no `_focus` call at all, and neither does `restore`
(`:1800-1852`).

**d. The violation: `sb workspace new --focus`.**

```
$ ./bin/sb workspace new --help
usage: sb workspace new [-h] [--json] [--task TASK] [--role ROLE]
                        [--name AGENT] [--base BASE] [--focus] [--no-board] [name]
```

`switchboard/cli.py:255` → `cli.py:846` → `broker.workspace_new(focus=…)`
(`broker.py:588`) → `self._focus(lead, focus)` at `broker.py:633` and `:646`. The default
is `False`, so nothing focuses unless asked — but *asking* is exactly what "Focus as a
flag … nothing can ask for it" rules out, and this is a spawn path that is not `sb start`.
Present unchanged on main (`main` cli.py:255). `sb workspace new` is not human-gated, so
an agent can reach it.

**e. Weaker, judgement call: `sb start --no-focus`** (`switchboard/cli.py:112`). It lets
the one command that must focus not focus. It *declines* rather than *asks*, so it is not
literally the rejected shape, but the entry states `sb start` focuses without qualification.

**f. What I did not test.** I did not verify that herdr itself refrains from focusing as a
side effect of `agent start` or `pane split` — I read the `--no-focus` flags switchboard
passes and checked `herdr agent prompt --help` / `herdr agent start --help` for a focus
option (there is none), but I ran no spawn to observe focus behaviour. I ran no mutating
command at all: no agent was spawned, no pane created, nothing cleaned up.

### Gaps (one line each, buildable)

1. `switchboard/cli.py:255` — remove `--focus` from `sb workspace new`, and the `focus: bool = False` param at `broker.py:588` with its two `_focus` calls at `broker.py:633` and `:646`.
2. `switchboard/cli.py:112` — decide whether `sb start --no-focus` survives; the entry as written says `sb start` focuses, full stop.

---

## Out of my slice — one line each, not investigated

- `sb ask` and `sb wait` are still live verbs and `sb delegate` still has `--keep` / `--ephemeral`, and `sb cleanup` still has `--include-kept` / `--leave-children` (`./bin/sb --help`, `switchboard/cli.py`) — all on the explicitly-rejected list; belongs to whoever owns the commands slice.
- `board.open_beside` splits at `ratio=0.38` on `worker-2` (`switchboard/board.py:379`); main's `e8e5c70` changed the sizing. Nothing in DESIGN-TRUTH fixes a width, so this is not a finding.
