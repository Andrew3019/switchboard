# Can switchboard be exercised from a non-installed build, with its own state?

Yes — today, with no code changes. Proven by experiment (below), not just read from source.

## What actually isolates you, and why

`sb` on PATH (`/Users/andrew/.local/bin/sb`) is a symlink to `/Users/andrew/Code/switchboard/bin/sb`
(the main checkout). That entrypoint script does:

```python
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))
```

`os.path.realpath(__file__)` follows the symlink back to the main checkout, so *every* pane on
this machine that types the bare word `sb` — regardless of which worktree it is `cd`'d into —
runs the main checkout's Python, because that's the only thing on PATH. This is the actual bug
described in the brief: worktrees never get their own code.

But every worktree (and every plain `git clone`) already has its **own**, non-symlinked
`bin/sb`. Run that file *directly* — `./bin/sb ...` or a PATH that points at that worktree's
`bin/` instead of `~/.local/bin` — and `realpath` resolves to that checkout, so it imports
`switchboard.cli` from that worktree's branch. **No env var, no flag, nothing to build.** This
is the direct answer to "can a spawned agent be given a different `sb` on its PATH?" — yes,
trivially, by controlling which directory comes first on PATH (or shelling to the full path).
Confirmed: `phase-1` has a hidden `sb flush` verb (`switchboard/cli.py`, `cmd("flush",
hidden=True)`) that `main` does not. Running the PATH-installed `sb flush` from inside the
worktree gives an argparse error ("invalid choice: 'flush'"); running that same worktree's own
`./bin/sb flush` succeeds ("rang nobody"). Same repo, same cwd, different binary picked by
which `bin/sb` you invoke — proof the branch's code, not the installed one, is what runs.

State (`state.db`, `config.json`) is a separate question. `switchboard/store.py::repo_root()`
locates the store via `git rev-parse --git-common-dir`, resolved absolutely, specifically so
every worktree of one repo shares one store (comment at store.py:34-38: "Resolved by the tool,
never by an agent (P0)" — deliberate, not an oversight). There is no env var or CLI flag that
overrides `state.db`/`config.json`/plugin state root. (There *is* `SWITCHBOARD_DEFAULTS`,
`SWITCHBOARD_MODELS_CONFIG`, and `SB_PANEL_DIR` — none of them touch the store.) That means
worktrees of the *same* repo — e.g. this `isolated-instance` worktree against the main
checkout — cannot get isolated state; they're wired to share it on purpose.

A **separate `git clone`** sidesteps this cleanly: it has its own `.git`, so
`git rev-parse --git-common-dir` returns a different absolute path, so `store_dir()` resolves
to a different `state.db` with nothing in it. That's the isolated instance.

## Proof (experiment run and then torn down)

1. `git clone /Users/andrew/Code/switchboard <scratch>/switchboard-isolated-proof`, then
   `git checkout phase-1` inside it.
2. Confirmed separate store: `git rev-parse --path-format=absolute --git-common-dir` inside the
   clone pointed at the clone's own `.git`, not the main checkout's. `./bin/sb doctor` reported
   `store  <scratch>/switchboard-isolated-proof/.git/agentflow/state.db`. `./bin/sb status`
   said `(no agents)` — a fresh store, not the live fleet's 200+ agents.
3. Confirmed branch code: `./bin/sb flush` → `rang nobody` (phase-1 only); the PATH-installed
   `sb flush` from the main checkout → argparse error (verb doesn't exist on `main`).
4. Spawned a real throwaway agent from the isolated clone:
   `./bin/sb start 'sb block "proof agent, ignore" immediately, do nothing else'
   --name isolated-proof-lead --no-focus --no-board`.
   It came up, ran, and called `sb block` as instructed — visible in the isolated clone's own
   `sb status`.
5. Checked the **live** fleet from the real checkout: `sb status` (main, PATH-installed) did
   **not** list `isolated-proof-lead` anywhere — confirms state isolation holds.
6. Checked `herdr workspace list` (the one herdr daemon on this machine, shared by everything):
   it **did** list `isolated-proof-lead` as a workspace, right alongside `main-5`, `worker-2`,
   `isolated-instance`, etc. — confirms the herdr-level leak described below.
7. Cleaned up: `./bin/sb cleanup isolated-proof-lead --force` closed the agent and its herdr
   workspace; `herdr workspace list` no longer showed it. Deleted the clone directory
   entirely (`rm -rf`). Re-checked live `sb status` and `herdr workspace list` afterward —
   both unchanged from before the experiment, no residue.

## What does NOT get isolated — name it, don't assume it

- **herdr itself is one global daemon per machine**, spoken to over a socket API
  (`herdr workspace ...`). It has no per-instance scoping. An agent spawned from an isolated
  clone gets a real pane/workspace in the *same* shared herdr registry as the live fleet —
  visible via `herdr workspace list`, consuming a real workspace slot, subject to the same
  name collisions. If an isolated instance's agent name collides with a live one, herdr (and
  therefore `sb`) cannot tell them apart at that layer. This is the leak the brief asked to be
  named explicitly: it is real, and it is not fixable by anything switchboard controls — it
  would need a second herdr daemon (`HERDR_CONFIG_PATH`), which is out of scope here.
- `~/.herdr/worktrees/<repo>/<branch>` bookkeeping is herdr's own, global, per-user — not
  switchboard state, but still shared machine state that any isolated instance's worktrees
  would land in.
- `~/.config/switchboard/models.toml` (global model tiers) and `SWITCHBOARD_DEFAULTS`-pointed
  config are per-user unless explicitly overridden per clone.

## Bottom line

No new flag or code is needed for the two things asked in the brief:
- **"different `sb` on PATH"** — yes, already true, just point PATH (or invoke directly) at a
  worktree's own `bin/sb` instead of the symlinked installed one. This alone fixes the phase-1
  acceptance bug: children spawned *from* the branch worktree should get that worktree's
  `bin/` ahead of `~/.local/bin` on PATH, or call `./bin/sb` explicitly, rather than trusting
  the shell's default PATH order — inspect where the branch worktree's PATH gets threaded to
  spawned panes (`switchboard/herdr.py::start_agent` and whatever sets pane shell env) to make
  that the default rather than an operator having to remember it by hand.
- **A fully isolated instance (own state, own binary, invisible to the live fleet)** — yes,
  via a genuinely separate `git clone`, proven above. It costs nothing to build; it already
  works. The only caveat is the herdr layer: panes/workspaces are visible in the shared
  `herdr workspace list` and share herdr's naming space, so pick throwaway names that can't
  collide with live agents, and clean up promptly (`sb cleanup ... --force`, then delete the
  clone). That's a real but narrow leak, not a blocker.

I would not build anything new here. What's missing is process, not code: (1) document that a
branch under test needs its *own clone* (not a worktree of the same repo) to get isolated
state, since worktrees deliberately share the store; and (2) fix the actual phase-1 acceptance
bug by making spawned children inherit their parent worktree's `bin/` on PATH instead of
falling through to the installed symlink — that's the one concrete gap that let old code run
silently during the test hour.
