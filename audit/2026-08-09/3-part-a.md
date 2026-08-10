# Audit part A — cleanup mechanics, worktree teardown, restore

Tree audited: `/Users/andrew/.herdr/worktrees/switchboard/worker-2` (branch worker-2, HEAD
a9dd319). All files cited below are **byte-identical** in the `main` checkout
(`/Users/andrew/Code/switchboard`, caa6d20) — verified by `diff -q` on broker.py, cli.py,
store.py, herdr.py, defaults/protocol.md, defaults/roles/orchestrator.md. So the runtime
behaviour observed via the `sb`/`herdr` on PATH applies to the audited tree too.

Live probes run (both cleaned up, nothing left behind): `herdr tab create --cwd
/nonexistent/...` and `herdr workspace create` + close its only pane.

---

### line 196 — "**The orchestrator handles cleanup itself, and it should do this aggressively** — probably literally every agent that is done. Cleaning up an orchestrator always cleans its children."

**Verdict:** PARTIAL — (a) SATISFIED, (b) PARTIAL.

**Evidence (a) — the aggressive expectation IS in the prompt text an orchestrator receives:**
- `defaults/roles/orchestrator.md:147` — "`sb cleanup [names]` closes finished agents in
  your subtree. **Use it constantly, as part of the job rather than a tidy-up at the
  end**: closing costs only the pane…"
- `defaults/roles/orchestrator.md:150-153` — the rule is stated as what to KEEP: "Two
  things stay open, and nothing else does: an agent blocked waiting on a human, and
  finished implementation work someone may actually want to open… if you are unsure
  whether something is worth keeping, it is not." That is "literally every agent that is
  done", minus two named exceptions.
- `defaults/protocol.md:114` gives every agent the verb: "`sb cleanup [names]` closes
  finished ones beneath you".
- Scope really is the subtree: `switchboard/broker.py:2960` — non-human callers get
  `scope = self._descendants(me)`.

**Evidence (b) — "cleaning up an orchestrator always cleans its children" holds only for
the sweep, not for the named form:**
- Sweep (no names): `broker.py:2969-2971` — `candidates = scope`, i.e. every descendant,
  each closed if it passes its own gates. Here the children do go with the parent.
- Named (`sb cleanup <orchestrator>`): `broker.py:2969` — `candidates = [by_name[n] for n
  in names]`. **Only the named row is closed.** Nothing anywhere walks down to close
  finished children of a named agent — the only descendant logic in `cleanup` is the
  refusal gate `held` (`broker.py:2978-2987`, `live_descendants`), which counts *live*
  children only.
- So: a finished child with an open pane whose orchestrator is named is left with its pane
  open. A *live* child makes the close a refusal (`broker.py:2983-2988`), and
  `--leave-children` (`cli.py:238-241`) closes the parent and deliberately leaves them
  running — i.e. the one flag that touches children does the opposite of "always cleans
  its children".

**Gaps:**
- `sb cleanup <name>` does not cascade to that agent's finished descendants; make a named
  close sweep the subtree beneath it (`broker.py:2969`).
- Decide and document whether `--leave-children` is compatible with "cleaning up an
  orchestrator always cleans its children", or rename it to say it orphans them.

---

### line 206 — "**Cleanup closes the agents, closes the tab, and closes the entire space and deletes the worktree if everything else is closed too.** Work is usually pushed before its worktree is deleted."

**Verdict:** PARTIAL.

**Evidence — the four things:**
1. **Closes the agents** — SATISFIED. `broker.py:3055-3059`: `release_agent` then
   `close_pane`, then `set_state(..., "done")` and `pane_id=None`
   (`broker.py:3065-3069`). Same for the teardown path, `_stop_panes`
   (`broker.py:1804-1826`).
2. **Closes the tab** — SATISFIED, implicitly. Each agent gets its own tab
   (`herdr.py:255` `create_tab`, "A tab per agent"), and both panes in it are closed: the
   agent pane plus the board pane beside it (`broker.py:3064` and `1821`,
   `_close_board`). `_close_board`'s own docstring names the bug this fixed
   (`broker.py:744-747`): "a close that took only the agent's own pane left an empty tab
   behind once per agent". There is no `close_tab` call — the tab goes when its last pane
   does.
3. **Closes the entire space** — SATISFIED as a herdr side effect, but not by switchboard.
   `switchboard/herdr.py` has `create_workspace`/`rename_workspace` and **no**
   close/remove-workspace method (grep, herdr.py:282,377); `_deregister`
   (`broker.py:1829`) runs only `git worktree remove`. Probed live: created
   `herdr workspace create --label sb-audit-probe`, closed its only root pane, and the
   workspace vanished from `herdr workspace list`. So closing every pane does close the
   space — nothing in switchboard asks for it.
4. **Deletes the worktree** — SATISFIED, but **only in `sb workspace close`, never in `sb
   cleanup`**. `broker.py:1829-1878` `_deregister` names the one path (`git worktree
   remove <path>`, never a bare prune); `broker.py:1389` then `git branch -d` (never
   `-D`).

**Evidence — "if everything else is closed too":** the condition exists and is stronger
than the design states, but it is a *precondition the human must satisfy*, not an
automatic trigger:
- `_records_gate` (`broker.py:1468`) — no unfinished agent row whose cwd is under the
  checkout; `_filed_gate` (`broker.py:1478`) — none filed under the workspace name;
  `_live_under` (`broker.py:1583`) — no OS process at all in the directory, and "unknown
  is not empty" is a refusal (`broker.py:1458-1462`). Gate runs twice, before and after
  the panes come down (`broker.py:1329-1334`).
- **But nothing triggers teardown when the last agent closes.** `workspace_close` has
  exactly one caller in the whole codebase — `cli.py:879`, the human typing `sb workspace
  close`. And no prompt text anywhere mentions it: grep of `defaults/protocol.md`,
  `defaults/roles/*.md`, `defaults/prompts.toml` for "workspace close"/"worktree" returns
  nothing but `protocol.md:108`'s "a worktree nobody opens". So the sentence's subject
  ("cleanup") does the first two things; the last two are a different, human-only,
  never-automatic command.

**Evidence — the push half:** nothing pushes, and nothing mentions push.
- Grep for `push` across `switchboard/`, `defaults/`, `bin/` finds **no git push and no
  unpushed-work check anywhere** (only unrelated hits: broker.py:2471, herdr.py:563,
  board.py:312).
- What does exist is a commit-level guard: `_inventory_gate` (`broker.py:1509-1546`)
  refuses on `git status --porcelain --ignored` entries that are not `!!` — "That is work
  git can see, so commit or stash it and ask again" (`broker.py:1533-1535`) — and ignored
  files are listed and require `--yes` (`broker.py:1538-1546`).
- Committed-but-unpushed work is not warned about, but is not lost either: `git branch -d`
  (`broker.py:1389`) refuses an unmerged branch, which is then kept and reported
  (`cli.py:951-953`). The recovery path is therefore "the branch survives locally", not
  "it was pushed".
- Agents are told to commit (`defaults/protocol.md:106-107`, "commit your work, then call
  `sb done`… anything left uncommitted is invisible in a worktree nobody opens") but are
  **never** told to push.

**What `--force` bypasses:** `sb cleanup --force` (`cli.py:234-236`) lifts every gate on a
*named* agent — state, unread mail, herdr disagreement, keep-disposition
(`broker.py:3000-3021`) — and is illegal as a sweep (`broker.py:2966-2968`). It does
**not** lift the live-children gate (`broker.py:2981`, docstring 2944-2950) and has
nothing to do with worktrees. `sb workspace close` has **no `--force` at all** (verified:
`sb workspace close --help` → only `--yes`, `--resume`); `--yes` bypasses only the
ignored-file confirmation, i.e. it will delete a worktree's `.env`.

**Gaps:**
- Nothing tears down a workspace/worktree when its last agent closes; `workspace_close` is
  only ever reached from `cli.py:879` (human typing it).
- No prompt or role text tells any agent that `sb workspace close` exists, so the
  "aggressive cleanup destroys the worktree" story has no actor.
- Nothing pushes, and nothing warns that a worktree about to be deleted holds commits no
  remote has; add an unpushed-commit check (or a push) to `_inventory_gate`.
- `switchboard/herdr.py` has no close-workspace call — teardown relies on herdr
  auto-closing an empty workspace, undocumented in our code.

---

### line 248 — "**`sb restore` is gone if the worktree is gone.** Aggressive cleanup therefore destroys it, and that is accepted: the push is the recovery path for the work, not restore."

**Verdict:** BROKEN — not because restore survives, but because it does **not fail
cleanly**: it reports success and silently brings the agent back in the wrong directory.

**Evidence — what restore depends on:**
- `broker.py:3131` — a `session_id` on the row, else "has no session id; nothing to
  restore".
- `broker.py:3156` — `pane, _ = self._tab_for(wsid, ws.get("path") or a["cwd"] or
  str(self.repo))` — the recorded **cwd**, i.e. the worktree path.
- `broker.py:3163` — `self.h.start_agent(name, pane, resume=a["session_id"], ...)`; the
  transcript/session that `--resume` reads is bucketed by cwd:
  `store.py:1443-1444`, `Path.home()/".claude"/"projects"/slug(cwd)/f"{session_id}.jsonl"`.
- `broker.py:3146` — `_refuse_retiring(a["workspace"])` refuses only *while* the teardown
  mark is held; `store.retire_workspace` (`store.py:1079-1083`) clears `retiring`, so
  after the teardown finishes the refusal no longer applies.
- **No check anywhere that the recorded cwd still exists.**

**Evidence — what it does when the worktree is gone (measured):** herdr does not error on a
missing cwd, it silently substitutes `$HOME`. Probe on the live herdr:
`herdr tab create --cwd /nonexistent/audit-probe-xyz --no-focus` returned
`"cwd":"/Users/andrew"` with a normal `tab_created` result (pane closed again afterwards).
So `_tab_for` succeeds, `start_agent` runs `--resume <id>` in the human's home directory —
a different `~/.claude/projects` bucket from the one holding the session — and switchboard
then writes `pane_id`, clears `ended_at`, sets `state='working'` (`broker.py:3172-3179`)
and prints `restored <name>` (`cli.py:894`). The record says the agent is back and working;
the pane is in the wrong repo with no context.

**Evidence — the prompts assert the opposite of the design:** the "restore always works"
claim is stated unconditionally in text agents read, with no worktree caveat:
`defaults/protocol.md:115-116` ("closing costs only the pane: session, summary, messages
and transcript survive, and `sb restore` brings an agent back"),
`defaults/roles/orchestrator.md:148-149` (same), and `broker.py:2920-2922` in `cleanup`'s
own docstring.

**Gaps:**
- `restore` must check the recorded cwd still resolves and refuse with "its worktree is
  gone — the work is in branch X, restore cannot bring it back" (`broker.py:3156`).
- Guard against herdr's silent `$HOME` substitution for a missing `--cwd` in `_tab_for`
  (`broker.py:2340`) — every caller inherits it, not just restore.
- Restore of an agent whose workspace row is retired should be refused outright:
  `_refuse_retiring` only covers the in-flight teardown (`broker.py:3146`).
- Qualify "`sb restore` brings an agent back" in `defaults/protocol.md:115` and
  `defaults/roles/orchestrator.md:148` — true until the worktree is deleted, and the
  orchestrator is told to be aggressive about exactly that.

---

## Seen in passing (not mine, one line each)
- `cleanup` marks a force-closed row `done` even when the pane close FAILED
  (`broker.py:3040-3054`) — logged and printed, but the finished-state chain then carries a
  claim nobody confirmed.
- `defaults/protocol.md` tells agents to commit before `sb done` but never to push, which
  is the finish-reporting chain's problem as much as teardown's.
