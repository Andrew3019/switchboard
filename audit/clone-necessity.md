# Do we still need `git clone` for live verification?

Read-only investigation, tested live where the brief asked for testing. `DESIGN-TRUTH.md`
not touched. All test artifacts (a scratch collector process, a scratch store directory
under the live repo's `.git`) were created and torn down during this session; nothing was
left behind and the live fleet's collector (pid 40401) was re-checked after each experiment
and never lost polls or restarted.

## The one fact that decides it

**A worktree shares its repo's `git-common-dir`, and every path a clone is believed to
isolate — `store.repo_root()` for the store, `panel.Paths.resolve()` for the
collector/lock/snapshot — is derived from that same shared directory with no override for
the store and one narrow override (`SB_PANEL_DIR`) for the panel.** That is not inference;
it is what `switchboard/store.py:46-61` and `switchboard/panel.py:115-176` do, and it is what
running `./bin/sb doctor` from *this* worktree (`clone-necessity`) showed directly, with no
setup:

```
$ git rev-parse --path-format=absolute --git-common-dir
/Users/andrew/Code/switchboard/.git
$ ./bin/sb doctor
herdr 0.8.0 ok
store  /Users/andrew/Code/switchboard/.git/agentflow/state.db
panel  pid 40401 1 up, 25138 polls, 0 errors, last tick 53 ms, 1s ago
```

That is the *live* store (`state.db` in the main checkout's `.git`) and the *live* collector
(pid 40401, tens of thousands of polls — clearly long-running, not something this command
started). A plain worktree, today, with no flag and no env var, reads and would write into
the exact same store and shares the exact same collector as the main checkout and every
other worktree of this repo. This confirms the brief's suspicion for both #1 and #3 on the
believed-benefits list, and it is the reason a clone convention exists at all.

## What I actually tested, one claim at a time

### 1. Separate store — worktree alone does NOT give this; a redirect can

No code path lets you point `state.db` at a different file without changing
`paths.store_dirname`, and that setting is read at import time with `repo=None`
(`store.py:43`, `panel.py:83`), so the only lever is `SWITCHBOARD_DEFAULTS` — the env var
that replaces the whole shipped `defaults/` directory wholesale (`config.py:47`,
`defaults_dir()`).

Tested: copied `defaults/` (208K) to a scratch dir, changed one line
(`store_dirname = "agentflow-test"`), and ran with the env var pointed at the copy:

```
$ SWITCHBOARD_DEFAULTS=<scratch>/alt-defaults ./bin/sb doctor
store  /Users/andrew/Code/switchboard/.git/agentflow-test/state.db
$ SWITCHBOARD_DEFAULTS=<scratch>/alt-defaults ./bin/sb status
(no agents)
$ ./bin/sb status                          # unmodified, same worktree, no env var
AGENT              ROLE          STATE ...  # the real live fleet, unaffected
```

A genuinely separate `state.db` was created under the *same* shared `.git`, at
`.git/agentflow-test/state.db`, and the live store's agent list was checked before and after
and was unchanged. Cost: ~208K of duplicated `defaults/` and one edited line, versus a git
clone's ~28M and ~1.1s (`git clone -q` timed on this repo). Torn down with `rm -rf` on the
`agentflow-test` directory; confirmed gone.

**The catch:** `SWITCHBOARD_DEFAULTS` replaces the whole defaults layer, not just one
setting — `roles/`, `presets.toml`, `prompts.toml`, `protocol.md`, `models.toml` all come
from the same directory (`config.py:72-76`, `_shipped_settings`/`roles`/`prompts` all call
`defaults_dir()`). A real isolated agent run needs a full, current copy of all of it, not
just `settings.toml`, or spawn prompts and role definitions silently fall back to whatever
is (or isn't) in the copy. Drift is not silent, though: a required setting missing from a
stale copy raises `ConfigError` naming the key (`config.py:344-349`), not a quiet wrong
default — so the failure mode is "test breaks loudly," not "test passes against the wrong
config."

### 2. Code isolation — a worktree already gives this, trivially

This was never in question and I did not spend a test proving it: a worktree's working tree
is, by definition, checked out to its own branch. `clone-necessity` (this worktree) is on
branch `clone-necessity`; the main checkout is on whatever branch it has open. Nothing about
the store or collector affects this. A clone buys nothing here that a worktree doesn't
already have.

### 3. Collector isolation — worktree alone does NOT give this; `SB_PANEL_DIR` does, and the redirected-store approach gets it for free

Confirmed above: an unmodified worktree's `sb doctor` reports the live collector's pid.

Tested `SB_PANEL_DIR` alone (the env var `panel.Paths.resolve()` checks first,
`panel.py:98,173-176`):

```
$ SB_PANEL_DIR=<scratch>/panel-test ./bin/sb doctor
store  /Users/andrew/Code/switchboard/.git/agentflow/state.db      # still the LIVE store
panel  no collector — no panel snapshot yet — no collector has published one
```

This isolates the panel/lock/snapshot paths but leaves the store shared — it is a partial
tool, not a full substitute for a clone on its own.

Then tested whether the `SWITCHBOARD_DEFAULTS` redirect (above) *also* separates the
collector, since `panel.py`'s `_STORE_DIRNAME` is read the same way as `store.py`'s. It
does, and I proved it by actually starting an isolated collector process, not just reading
its resolved path:

```python
# with SWITCHBOARD_DEFAULTS=<scratch>/alt-defaults in the environment
paths = panel.Paths.resolve()          # -> .git/agentflow-test/panel
panel.ensure_collector(paths)          # -> True (a collector was launched)
panel.collector_running(paths)         # -> True, 1.5s later
```

`ps` showed the new process (pid 81298) holding `flock` on
`.git/agentflow-test/panel/collector.lock` — a different file from the live collector's lock
on `.git/agentflow/panel/collector.lock`. The live collector (pid 40401) was checked
immediately after and its poll count had kept advancing normally — the new collector did not
contend for the lock, steal it, or otherwise disturb the live one. I then killed the test
collector (`kill 81298`) and deleted `agentflow-test`; the live collector's poll count kept
advancing afterward too, confirming no side effect either way.

**One nuance found by tracing the code, not by triggering it live:** the collector's
doorbell/reconciler subprocess picks its working directory from `main_checkout`
(`collector.py:399-423`, `_doorbell_cwd`), which is read from the *isolated* store's
`config.json`. A fresh isolated store has no `config.json` yet, so this falls back to
`store_dir.parent.parent` — which is the shared `.git`'s parent, i.e. **the main checkout**,
not the worktree under test. `tests/test_panel.py::test_a_collector_started_in_a_worktree_rings_from_the_main_checkout`
shows this is deliberate behavior for the *ordinary* (non-isolated-store) case, where the
main checkout genuinely is the right place to run `sb flush`. For an isolated-store test
that wants the doorbell's own `sb` subprocess to run inside the worktree instead, the setup
needs one extra step: `store.write_config({"main_checkout": <worktree path>}, cwd=<worktree>)`
against the isolated store, before the collector starts. I did not fire the doorbell itself
in the isolated setup to confirm this end to end — flagging it as traced-not-tested, and as
the one place this recipe needs an explicit step rather than working by default.

## What neither a clone nor the redirect fixes: pane/board visibility

Already established by a prior investigation (`audit/isolated-instance.md`, its own live
test) and separately observed today per the brief: herdr is one daemon per machine with no
per-instance scoping. `herdr workspace list` shows every pane from every workspace,
regardless of which store or collector that pane's `sb` talks to. A clone's agents get their
own store; they do not get their own line item hidden from `sb inspect`/`herdr workspace
list` — they show up in the same shared registry as the live fleet, under whatever name they
were given. This is true of the redirected-store worktree approach too, for the same reason:
nothing about either isolates herdr itself.

## The house-rules line that overstates it

`.switchboard-shared/presets/house-rules.md:45-47`:

> Isolate with `git clone` of this repo into a scratch directory — a clone gets its own
> state automatically, via git's common dir. Check out your branch there and drive that
> clone's own `./bin/sb`. **Agents you spawn there are invisible to the live fleet.**

The bolded clause is true of the *store* (`sb status` in the main checkout will not list
them — confirmed live, above and in `audit/isolated-instance.md`) and false of the *board*:
`herdr workspace list` lists them right alongside the real fleet's agents
(`audit/isolated-instance.md`'s own experiment, step 6). It should say something closer to:
"invisible to the live fleet's `sb status`/records — still visible in `herdr workspace
list`/`sb inspect`, so give them throwaway names that can't collide with a live agent's."
This is not my document to edit (a researcher reports, doesn't act, and this file isn't
`DESIGN-TRUTH.md` anyway) — naming it here so whoever owns house-rules.md can fix the line.

## Recommendation

**Default to a worktree with a redirected store (`SWITCHBOARD_DEFAULTS` pointed at a
maintained copy of `defaults/` with `store_dirname` changed), not a clone**, for the common
case of verifying a fix that touches ordinary `sb` behavior — spawning, messaging, status,
board rendering logic, most of what a `worker`/`qa`/`researcher` role's fix touches. It is
cheaper (208K + a env var vs. 28M + a clone), it needs no second checkout to keep in sync
with a branch (a worktree already tracks the branch under test), and it is what the codebase
already supports without new code — `SWITCHBOARD_DEFAULTS` and `SB_PANEL_DIR` are existing,
tested escape hatches, not something this investigation invented.

**Keep clones for the narrower set of cases the brief anticipated: anything that tests the
collector's own election, restart, or doorbell-timing behavior end to end**, where the
`main_checkout`/doorbell-cwd nuance above means the redirect needs an extra, easy-to-forget
setup step to behave identically to a real separate repo, and where a clone's guarantee (a
*genuinely* different `git-common-dir`, not a same-directory-different-subfolder trick) is
worth the extra weight because the exact thing under test is path/directory identity itself
(`audit/phase3.7-scope.md`'s collector-staleness work is exactly this shape — it already
uses a clone, correctly). A rule that can actually be applied: **reach for a clone only when
the change under test touches `collector.py`, `panel.py`'s `Paths`/`ensure_collector`, or the
doorbell/reconciler timing; use a worktree + redirected store for everything else.**

What I tested live, versus what I read from code and existing tests:
- **Tested live:** worktree shares store and collector by default; `SB_PANEL_DIR` isolates
  the collector alone; `SWITCHBOARD_DEFAULTS` with a modified `store_dirname` isolates both
  store and collector together, with the live fleet's own collector and store checked
  before/after and unaffected; disk/time cost of a clone on this repo.
- **Read from code / existing tests, not independently re-triggered:** the `main_checkout`
  fallback path in `_doorbell_cwd` (traced against `collector.py` and confirmed consistent
  with `tests/test_panel.py::test_a_collector_started_in_a_worktree_rings_from_the_main_checkout`,
  but I did not fire a live doorbell against an isolated store to watch it happen); the herdr
  pane-visibility leak (relied on `audit/isolated-instance.md`'s own live experiment rather
  than re-running it, since the brief says it was already observed today).
