# A spawned agent now runs its own checkout's `sb`

## The bug

`sb` on PATH is `~/.local/bin/sb`, one symlink per machine into `/Users/andrew/Code/switchboard/bin/sb`.
`bin/sb` puts `os.path.realpath(__file__)/..` on `sys.path`, and `realpath` follows the
symlink back to the main checkout — so every agent in every worktree ran the MAIN
checkout's code, whatever branch its own worktree had out. Phase 1 was merged onto
`phase-1` and acceptance-tested against a build that did not contain it.

## The fix

`broker._pin_sb`, called from the two places an agent is started — `delegate` and
`restore` — just after the pane is known and **before** the name is claimed:

1. `pane run` types `export PATH=<checkout>/bin:"$PATH"; echo "sb=$(command -v sb)"`
   into the pane's shell, which is the shell `agent start` then launches the provider CLI
   in. The agent and every shell it spawns inherit it.
2. `pane wait-output --match sb=<checkout>/bin/sb --source recent-unwrapped` reads back
   where `sb` actually resolved. `pane run` is accepted whether or not a shell was there
   to take it, so without this the fix would have the same silent failure as the bug.
3. Two attempts, then `SbUnpinned` — the spawn is refused rather than producing an agent
   quietly running the wrong build.

Nothing is installed, the symlink is untouched, and no PATH outside a spawning pane moves.
A checkout with no `bin/sb` of its own (any other project) is skipped entirely: no herdr
calls, PATH untouched.

Why before the claim: a refusal then costs no row and no held name, and the wait stays
outside the window `status.SPAWN_GRACE` covers, so no spawn-timing constant moves.

Why the marker is `sb=<path>`: the typed line is echoed into the same pane and contains
the bin directory, so a marker that appeared in it would confirm itself. `sb=<path>/sb`
appears only in the output.

Knobs: `[timeouts] pin_ms = 5000`, `[retries] pin_attempts = 2` in `defaults/settings.toml`.

## The proof

Run in a throwaway `git clone` of the repo (a clone gets its own `.git`, so
`git rev-parse --git-common-dir` gives it its own store — the method from
`audit/isolated-instance.md`), checked out on this branch, driven by the clone's own
`./bin/sb`. The distinguishing verb is `sb flush`, hidden, present on `phase-1` and absent
from `main` — and the main checkout, which the installed symlink points at, is on `main`.

- Installed `sb flush` → `argparse: invalid choice: 'flush'`.
- `./bin/sb start '... run `command -v sb` and `sb flush` ...' --name sbpinproof`
  spawned a real agent in the clone.
- That agent, typing the bare word `sb`, reported:
  `command -v sb` → `<clone>/bin/sb`, and `sb flush` → `rang nobody`.
  It ran the clone's build, not the installed one.
- The clone's store logged `sb_pinned {"pane_id": "w26:p1", "path": "<clone>/bin"}`.
- The live fleet's `sb status` never listed `sbpinproof`. The one leak is herdr's own:
  the pane showed up in the shared `herdr workspace list`, exactly as
  `audit/isolated-instance.md` says it would.
- Cleaned up: `sb cleanup sbpinproof --force`, then the clone directory deleted. Both
  re-checked afterwards.

Also verified by hand against the live herdr binary before relying on it: `pane run` +
`pane wait-output --source recent-unwrapped` matches the printed path and exits 0.

## What this does NOT change

Nothing for agents already running. Their PATH was set when their pane was created and is
not revisited, and this code only runs on `fix-sb-path` — the installed symlink still
resolves to the main checkout on `main`. Phase 1 comes into force for the live fleet only
once the main checkout itself is on a branch carrying this, and even then only for agents
spawned after that point.
