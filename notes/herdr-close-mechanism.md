# Why closing one herdr workspace took the whole daemon down — mechanism and prevention

Read-only. Sources: `switchboard/` at `/Users/andrew/Code/switchboard` (working tree, not
this worktree, to see the real production code — this worktree's own copy is identical for
the files cited), herdr's own source checkout at `/Users/andrew/Code/herdr` (git HEAD
`69a07fdf0`, `Cargo.toml` version `0.8.0` — **matches** the installed binary's `herdr
0.8.0` exactly, confirmed with `herdr --version`), `~/.config/herdr/herdr-server.log`,
`~/.config/herdr/session.json` (current live state, read only), and
`notes/tasks/codex-probe-identity-and-turn.md` on the `codex-support` worktree (read-only,
not written to). No state-changing command was run.

## 1. Can switchboard itself trigger this? — **No, not through any normal `sb` verb.**

Searched every call switchboard makes into herdr for the word `workspace` combined with
`close`. There are exactly two kinds of hit:

- **`switchboard/broker.py`'s own `workspace_close` (line 1673)** — this is `sb workspace
  close`'s implementation, and it is a *switchboard* concept: a recorded git-worktree
  checkout, unrelated in code to herdr's own "workspace" (a TUI tab-group). It resolves to
  one of three routes — `_close_bare` (line 1760), `_close_gone` (line 1799), or
  `_close_checkout` (line 1829) — and **all three**, and only these three, close panes by
  calling `self._stop_panes(name, ...)` (line 2334), which calls `h.release_agent` and then
  a per-pane `pane.close` (`switchboard/herdr.py:422-423`, `self._call("pane", "close",
  pane_id)`) once per agent row. `_close_empty_spaces` (`broker.py:4364`), the code that
  makes `sb cleanup` also retire a workspace once every agent in it is gone
  (`broker.py:4317` calls it at the tail of `cleanup`), goes through this exact same
  `workspace_close` method (`broker.py:4414`). **`switchboard/herdr.py` — the one module
  that is allowed to speak herdr's protocol at all — contains no call to herdr's
  `workspace close`/`workspace.close` verb anywhere.** Grepping `herdr.py` for `"workspace"`
  turns up only `workspace create` (line 380) and `workspace rename` (line 469).
- **`acceptance/accept.py:297`**, inside `Clone._close_workspaces` — a **test-harness-only**
  teardown helper for the throwaway `git clone` instances the "Live proof" testing
  methodology in this repo's own protocol instructs agents to use (the same methodology
  this task's rules point at). It does call the real herdr binary's `workspace close`
  (`herdr_call("workspace", "close", w["workspace_id"])`), filtered to workspaces whose
  `repo_root`/`checkout_path` is under the clone's own directory. This is the **only**
  place in the whole repository that calls the vulnerable verb outside a human typing it by
  hand. See §4 for why it is contained rather than a second live version of the outage, and
  the one respect in which it still is not entirely safe.

**Plain answer: an ordinary `sb cleanup`, `sb workspace close`, or any fleet-facing
switchboard command never issues herdr's `workspace close`. It only ever closes individual
panes one at a time.** So the mechanism that killed the fleet on 2026-08-16 is not something
"any normal `sb` operation" can reach. It requires an agent (or a human) to run the raw
`herdr workspace close <id>` command directly, bypassing switchboard — which is exactly what
`probe-identity` did, per its own task instructions to "Tear down every pane, session and
file you create (`codex delete --force <id>`, `herdr workspace close`)"
(`codex-probe-identity-and-turn.md:45`). **Proved**, from reading every call site.

## 2. What is the mechanism? — **Proved from source, and reproduced in the live session state right now.**

Source is fully reachable (`/Users/andrew/Code/herdr`) and its `Cargo.toml` version matches
the running binary exactly, so this is read against the actual code in play, not a nearby
version.

`herdr workspace close <id>` calls the server handler
`src/app/api/workspaces.rs:298 handle_workspace_close`, which does:

```rust
self.state.selected = index;          // sets the GLOBAL selected-workspace index
self.state.close_selected_workspace(); // then closes "the selected workspace"
```

`close_selected_workspace` (`src/app/actions.rs:1670`) is **not** "close the one workspace
you were asked for." It first asks whether the workspace shares a **worktree-space group**
with other open workspaces:

```rust
let close_indices = self.workspaces.get(self.selected)
    .and_then(|ws| ws.worktree_space())
    .filter(|space| !space.is_linked_worktree)
    .map(|space| {
        self.workspaces.iter().enumerate()
            .filter_map(|(idx, ws)| ws.worktree_space()
                .is_some_and(|m| m.key == space.key).then_some(idx))
            .collect::<Vec<_>>()
    })
    .filter(|indices| indices.len() >= 2)
    .unwrap_or_else(|| vec![self.selected]);
```

`indices.len() >= 2` fires → **every** workspace sharing that `key` is closed together, all
of their panes torn down in the same call, not just the one named. If the filter doesn't
fire (fewer than 2 in the group, or the closed workspace's own `worktree_space.is_linked_worktree`
is `true`), only the one workspace closes — the safe, expected case, and the overwhelmingly
common one.

`space.key` is `WorktreeSpaceMembership.key`, computed in
`src/workspace/git/discovery.rs:71-99` as `canonicalize(git_common_dir)` — **the `.git`
directory shared by a repo's primary checkout and every `git worktree add`-created worktree
of it.** `is_linked_worktree` is `git_dir != git_common_dir` — true for a `git worktree
add` worktree, false for the repo's own primary checkout. In other words:

**Closing a herdr workspace whose cwd is a repo's *primary* checkout (not itself a `git
worktree`) silently takes down every other herdr workspace anywhere on the machine whose
cwd is any worktree of that same repository — because herdr treats "primary checkout +
its worktrees" as one group, and closing the primary closes the whole group at once.**

This is **exactly** the shape of the outage: not "2 panes for w1H6," but "~20 panes across
many unrelated workspaces/agents" (the sibling investigation's own count). A worktree-group
close is the one operation in herdr's whole close path that touches multiple workspaces'
panes in a single synchronous call, which is what produces a burst of near-simultaneous
`Hangup`/`Terminate`/`Kill` pane exits landing within the same handful of milliseconds —
matching the log.

**Confirmed live, right now, read-only, via `~/.config/herdr/session.json`** (the daemon's
current persisted state — not touched, only read):

```
wZ    cwd=/Users/andrew/Code/switchboard                                         key=…/switchboard/.git linked=False
w1GX  cwd=/Users/andrew/.herdr/worktrees/switchboard/codex-support                key=…/switchboard/.git linked=True
w1HE  cwd=/Users/andrew/.herdr/worktrees/switchboard/herdr-outage-prevention      key=…/switchboard/.git linked=True
w1HF  cwd=/Users/andrew/.herdr/worktrees/switchboard/agent-handoff-wording        key=…/switchboard/.git linked=True
w1HG  cwd=/Users/andrew/.herdr/worktrees/switchboard/board-awaiting-keypress      key=…/switchboard/.git linked=True
```

Five live workspaces share one key, `wZ` is the non-linked one. **This exact grouping
condition — the one the source shows triggers a multi-workspace close — is present on the
live fleet at the moment this was written.** Closing `wZ` with `herdr workspace close`
right now would, per the code, take all five (every active agent worktree under
`switchboard/` currently open in herdr) down in one call. Not run — read-only rule — but the
precondition is not hypothetical; it is the board's actual current state.

**What is still not proved:** *why the whole server process* went silent for ~4.1s and then
respawned as a brand-new process (fresh pid opening a new `herdr.sock`), rather than the
daemon surviving a burst of ~20 pane exits the way it evidently survives ordinary
one-at-a-time pane closes (§3 has a clean example of 5+ sequential closes with no incident).
No panic, fatal, or signal string appears anywhere in the log, and I found no code path in
`handle_workspace_close`, `close_selected_workspace`, or `shutdown_detached_terminal_runtimes`
(`src/app/runtime.rs:43`) that panics, aborts, or calls `process::exit`. I did not trace the
async pane-exit reaper or the terminal-runtime shutdown path exhaustively enough to rule out
a panic there under a 20-pane burst, or an external cause (OS-level, e.g. a resource limit
or a supervisor watching the socket) — **that piece is inferred, not proved**: the
worktree-group-close bug fully explains *which* and *how many* panes died and *why they died
together*; it does not by itself prove *why the server process exited*.

## 3. Is it the close specifically, or the workspace? — **The close (and its state at the moment), not `w1H6` itself. Proved.**

`w1H6` was closed **twice**. The first close, `10:14:48.284913Z`, is the crash. `w1H6`
reappeared moments later from the persisted-state respawn (same id, restored by
`persist.restore`), stayed open through the rest of the morning, and was closed **a second
time** at `10:37:45.132149Z` — with **no incident**: exactly 2 panes exited (`pane_id=18,
19`, both `Hangup`), two ordinary `PaneDied for unknown pane` warnings (the same warning
the outage log shows — see below), and the server kept running uninterrupted, going on to
close four more workspaces one after another in the next ~9 seconds (`w1GH`, `w1GD`, `w1G8`,
`w1FZ`) each taking down only its own 1-2 panes, no cascade, no gap in the log.

That rules out "something about `w1H6`'s own contents" (the interrupted-then-restarted
`codex` subprocess the sibling investigation flagged as a candidate) as the cause: the same
workspace id, closed a second time, was completely safe. What differed is external to
`w1H6`: at `10:14:48` it evidently shared a worktree-space group with ≥2 members (per §2's
mechanism) and by `10:37:45` it evidently did not — plausible given `herdr`'s
`worktree_space` field is a **cache** that is not populated for every workspace at all times
(`session.json` right now shows 5 of 10 live workspaces with `worktree_space: null` despite
several of them sharing a cwd with grouped ones — the cache appears to populate only for
workspaces that have been focused/refreshed recently, not universally). I did not find and
did not have time to trace the exact refresh trigger, so **"the group was populated at
10:14:48 and not at 10:37:45" is inferred from the outcome, not read directly from a log
line naming group membership at either moment** — but it is the only difference the
mechanism in §2 depends on, and the two closes' outcomes are exactly what that mechanism
predicts if the cache states differed.

One more thing this settles, incidentally: the sibling investigation flagged the `PaneDied
for unknown pane` warnings next to `w1H6`'s two own panes as possibly diagnostic of a race
that caused the crash. The 22:51:35 log (an entirely ordinary, single-pane `pane.close`
the evening before, no incident) shows the **same warning firing on every ordinary pane
close** — it is not evidence of anything unusual; it is the routine shape of herdr's
async reap racing its own synchronous close, present in both safe and unsafe closes alike.

## 4. Prevention

**Herdr-side (needed, not switchboard's to fix):** `close_selected_workspace`'s
worktree-group expansion silently multiplies the blast radius of a single-id API call
without the caller asking for it or being told. At minimum this needs to not be silent to
an API caller — `handle_workspace_close`'s response reports only the one `workspace_id` it
was asked to close (`workspaces.rs:322-328`), never the others actually taken with it, so
nothing in the API response itself would have told `probe-identity` that its `w1H6` close
just took ~20 unrelated panes down. Ideally the API path should not apply the group-expand
at all — it reads as a TUI convenience (closing the tab you're looking at also cleans up
its sibling tabs) that has no business firing on a scripted, single-id API call from a
tool that never selected anything in a UI sense.

**Switchboard-side, concrete:**

1. **Nothing to fix in the live-fleet code path** — it already never calls `workspace
   close` (§1). No change needed there; this is the reassuring half of the answer.
2. **`acceptance/accept.py:297`** (`Clone._close_workspaces`) is the one place in the repo
   that does call it, using the real global herdr socket. It is contained today because a
   throwaway clone is its own git repository with its own `.git`, so its worktree-space
   `key` cannot collide with the live fleet's `switchboard`/`herdr` repos — but nothing
   in the code enforces that invariant, and this is exactly the kind of assumption that
   held right up until it didn't. Concretely: `_close_workspaces` should assert (and log,
   not silently trust) that every workspace it is about to close resolves its `worktree`
   info to a path under the clone's own root before calling `herdr_call("workspace",
   "close", ...)` — it already computes `mine`/`home` and filters on `paths`
   (`accept.py:288-290`), so the data needed for that assertion is already in hand; it
   just isn't checked against what herdr's `worktree_space` grouping could actually do.
3. **Task-instruction level**: `codex-probe-identity-and-turn.md:45` told the probing
   agent to use `herdr workspace close` directly as its own teardown step, with no warning
   that herdr's own daemon is machine-global and un-sandboxed (a fact the sibling
   investigation already flagged as a documentation gap). Any task text anywhere in this
   repo that tells an agent to run `herdr workspace close` (or any raw `herdr` teardown
   verb) by hand should say plainly: *"this can close other agents' work if your workspace
   shares a git checkout family with anything else open — prefer `sb workspace close` /
   `sb cleanup`, which never call it."* That's a one-line addition to whatever task
   templates instruct agents on teardown, not a code change.

## Recommended prevention, and what it costs if wrong

**Recommended: (3) first — fix the task-instruction gap immediately (zero cost, no code
risk, stops the one proven trigger), paired with (2) — harden `accept.py`'s teardown with
the path assertion (small, contained, testable change to test-only code). Leave (1) as
confirmation that no code change is needed on the switchboard side, and treat the herdr-side
fix as a separate, upstream ask (file it, don't attempt it from here — no access to publish
a fix to that repo was verified as part of this task).**

**What it costs if this is wrong:** if the task-instruction fix is insufficient — i.e., an
agent (or `sb` itself, unexpectedly) still finds a path to a raw `herdr workspace close`
call on a non-linked checkout with live worktree siblings — the outage recurs exactly as
before, because the actual bug (§2) is unfixed and unfixable from switchboard's side; the
mitigations here only reduce how a fleet agent gets there, not whether herdr does the
dangerous thing once asked. The live evidence in §2 says that precondition exists on the
board right now, so the residual risk this leaves in place is not small until the herdr-side
behavior itself changes upstream.
