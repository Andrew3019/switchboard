# Phase 3.7 scope — the collector runs stale code

Read-only audit. Base: this branch's tip, `scope-3.7` off `main` at `5998a43`. Written to
turn BUILD-PLAN.md's 3.7 row and `audit/phase3-scope.md`'s own 3.7 section (already a
solid first pass) into something someone can build straight from: a decision with a single
deciding reason, concrete pass/fail tests, and a restart-safety answer. Nothing here
contradicts the prior audit; it goes one level deeper on the same finding.

---

## 1. How the collector actually works today

**Who starts it.** Every renderer — in this codebase, only `board.py:main()` — builds a
`panel.Supervisor` (`board.py:451`) and calls `sup.tick()` on its own draw loop
(`board.py:352`, `refresh()`). `Supervisor.tick()` (`panel.py:491-497`) stamps `demand`
(the collector's own liveness signal) every call, then calls `panel.ensure_collector`
at most once per `panel.spawn_cooldown` (5.0s, `defaults/settings.toml:435`).
`ensure_collector` (`panel.py:432-473`) first checks `collector_running` (`panel.py:382-405`,
an flock probe that creates nothing) and, only if nobody holds the lock, `Popen`s
`python -m switchboard.collector` detached (`start_new_session=True`), with `PYTHONPATH`
set to `Path(__file__).resolve().parent.parent` (`panel.py:456`) — **the renderer's own
checkout**, not a configured or canonical one. This is the mechanism behind the
per-worktree ambiguity in §3 below: whichever worktree's board pane wins the race to spawn
is the checkout the collector runs, for its whole life.

**What the lock covers.** `Paths.resolve()` (`panel.py:171-176`) keys the lock, snapshot,
and demand file off `git_common_dir` (`panel.py:115-148`) — the *shared* `.git`, the same
for every worktree of one repo. `acquire()` (`panel.py:347-370`) takes an `flock(LOCK_EX |
LOCK_NB)` on `collector.lock` inside that shared directory and holds the fd for the
process's entire life (`collector.py:312-325`, `run()`'s docstring: "the lock is held by
the fd for the whole of this function"). One repo, one collector, regardless of how many
worktrees have panels open — confirmed by `panel.py`'s own module docstring line 41-45 and
by `tests/test_panel.py::test_only_one_collector_can_hold_it`.

**What its tick does.** `collector.run()` (`collector.py:312-356`) loops `tick()`
(`collector.py:283-309`) every `interval` (`display.board_refresh`, 2.0s,
`defaults/settings.toml:391`) until either `max_ticks` is hit, `_nobody_is_looking()`
returns true, or a signal sets `stop`. Each `tick()`: calls `snapshot()`
(`collector.py:134-159`), which opens a **fresh** `store.connect(readonly=True)` per tick
(closed in a `finally`, `collector.py:159`) and calls `status_mod.collect(db, Herdr(),
reap=False)` (`collector.py:155`); on success it calls `ring_doorbell()`
(`collector.py:162-211`, gated by `DOORBELL_GAP` = 10.0s and `any(a.ringable for a in
snap.agents)`), which spawns `sb flush` as a **fresh subprocess** in a daemon thread
(`_run_doorbell`, `collector.py:270-280`); then it publishes the envelope
(`panel.publish`, `collector.py:308`) whether the tick succeeded or failed.

**What ends it.** Only `_nobody_is_looking()` (`collector.py:359-371`): once `demand`'s
mtime is older than `panel.collector_idle_exit` (60.0s, `defaults/settings.toml:431`), the
next `tick()`'s loop check breaks and `run()` returns, releasing the flock in its `finally`
(`collector.py:355-356`). A signal (`SIGINT`/`SIGTERM`/`SIGHUP`) does the same thing
faster: `_stop_on_signal()` (`collector.py:374-387`) just sets the same `stop` event, so the
current tick finishes, the lock releases, and the process exits — this is the existing,
already-clean shutdown path, not a hazard to design around.

**Exactly where its source is read.** Once, implicitly, at process start — the moment
`python -m switchboard.collector` imports the module. `collector.py`'s own module
docstring says this is deliberate (lines 13-22: "this process outlives the code it started
with... anything it writes is written by a version nobody is running any more"), but it is
deliberate for the **store schema** (drift there is destructive — `readonly=True` and
`reap=False` exist to stop a stale reader from migrating or reaping against a live
store) — not for the collector's own decision logic. Nothing re-imports or re-execs after
that: `status`, `store`, and `herdr` are imported once (inside `snapshot()` via `from . import
store` / `from .herdr import Herdr`, `collector.py:146-147` — Python's `sys.modules` cache
means this binds the already-loaded module object on every call, it does not re-read the
file from disk). So **every** file transitively imported by `collector.py`'s read path —
not just `collector.py` and `panel.py` — is frozen at that one moment: `status.py`,
`store.py`, `herdr.py`, `config.py`, and whatever those import.

**This is the actual mechanism of the reported incident, and it is narrower than
"the doorbell runs old code" suggests.** `ring_doorbell` itself does none of the deciding —
it spawns `sb flush`, a brand-new process that runs whatever is on disk *right now*,
fixes included. The stale logic that decided *whether* to ring is `AgentStatus.ringable`
(the predicate `ring_doorbell` checks, `collector.py:195`) and `status_mod.collect`'s
undelivered-counting (`status._undelivered_counts`, per `collector.py:177-178`) —
both live in `status.py`, imported once, frozen for the collector's whole life. A fix to
`status.py`'s idea of who is ringable is exactly as stale as a fix to `collector.py`
itself, for as long as the same collector process runs. **Any fix to "what counts as
changed" has to cover `status.py` too, not just the two files `audit/phase3-scope.md`
named** (`collector.py`/`panel.py`); see §3.

---

## 2. Pass/fail tests

The plan's pass condition: *"after a doorbell fix lands on the running checkout, the next
tick behaves per the new code."*

### Test A — automatable in `tests/`, unit-level

Set up: instantiate `collector.run()` the same way `tests/test_panel.py`'s
`CollectorLifecycle` class already does (`_run()` helper at `test_panel.py:474-483`,
mocking `collector.snapshot` and `store.db_path`, `interval=0.0`, `max_ticks=N`) — but also
mock whatever function this fix adds (call it `collector.source_signature()` or similar) to
return one value for the first `k` ticks and a different value after, the same way
`_run()`'s `snapshot_returns` list already varies per call.

Change: the mocked signature function's return value, mid-run.

Observe: `run()`'s return code and `panel.collector_running()` afterward.

Pass: `run()` returns (the loop exits) at the tick where the signature first differs, the
flock is released (`collector_running()` is `False` after), and — this is the part that
makes it a real regression test and not just "it exits" — the number of ticks actually
executed before exit matches expectation exactly (no off-by-one, no waiting for the *next*
signature check after the one that changed).

This can be written today, without deciding *what* the signature is: give the mocked
function an opaque return value (a string or int) and assert only that "changed → exit,
unchanged → keep going," the same abstraction level `test_a_tick_publishes_the_tree...`
already tests at. `tests/test_panel.py`'s `CollectorLifecycle` class is the right home —
it already has the harness.

### Test B — needs a live isolated clone (mirrors BUILD-PLAN's own pass condition)

Set up: `git clone` this repo into a scratch directory (per the house rule — never run a
clone's `sb` from outside the clone). Check out a commit *before* a known, reproducible
`status.py` `ringable`/`undelivered` bug (or, simpler, temporarily hand-edit
`status.py`'s `ringable` property to always return `False`, to manufacture a
deterministic "doorbell should have rung but the running process won't" condition without
needing a real historical bug). Open a board pane in the clone (`./bin/sb`'s board, or
whatever starts one) so a collector elects itself and keeps running.

Change: with the collector still running, edit `status.py` in the *same clone* to fix the
manufactured bug — a plain file edit, deliberately **not committed**, matching the brief's
instruction that an uncommitted edit on disk is the actual failure case. Then create the
condition that should now ring the doorbell (e.g. leave mail undelivered for an agent).

Observe: does the *next* tick ring? Time it.

Pass: within one check interval of the fix's mtime, the doorbell rings using the new
logic — observable either directly (the mail is delivered) or via `sb doctor`'s panel line
(`panel.doctor_line`, `panel.py:505-539`) showing a fresh `pid` (proof the process
restarted) after the edit.

Fail: today's behaviour — the doorbell never rings for this condition until the pane is
closed for 60s and reopened, i.e. a human intervention, not a mechanism.

This is the one that actually proves the incident is fixed, because it reproduces the
literal condition (`git pull`/edit landing under a live collector) rather than a unit-level
stand-in for it.

### Test C — needs a live isolated clone, restart-safety specific

Set up: same clone as B, collector running, with a doorbell condition ready to fire
(an agent whose mail is undelivered and `ringable`).

Change: edit a watched file (triggering the exit-and-restart) at the same moment a doorbell
`sb flush` is in flight in its daemon thread — arrange this by making the ready-to-ring
condition true *before* the edit, so the tick that notices the changed signature is also a
tick that just spawned (or is about to spawn) a doorbell thread.

Observe: does the in-flight `sb flush` still complete and deliver? Does the new collector
come up clean, with no stuck lock?

Pass: the flush completes (it is a real subprocess, not a thread that dies with its
parent) and the new collector's first tick publishes normally. See §5 for why this is
expected to pass without new code.

---

## 3. The open decision: what does "the collector's code changed" mean

Four candidates, evaluated on the axis the brief calls out — how each behaves for an
**uncommitted edit on disk**, since that is what the failure case actually is (the running
process is stale relative to *whatever is in the working tree*, not relative to a ref).

| definition | cost per check | catches uncommitted edit? | catches worktree-B changes? |
|---|---|---|---|
| commit hash (`git rev-parse HEAD`) | one subprocess, ~5-10ms | **no** | no (and shouldn't — see below) |
| content hash of watched `.py` files | read + sha256 a few files, sub-ms to low single-digit ms | yes | no |
| max mtime of watched `.py` files | one `stat()` per file, ~0.01ms each | yes, with a narrow gap (see below) | no |
| a path/worktree-scoped key added to the lock/snapshot identity | changes *what counts as one collector*, not staleness detection | orthogonal — doesn't answer this question | yes, but changes the design (§3.1 below) |

**Commit hash is disqualified outright.** It answers "has HEAD moved," not "does the code
on disk match what I loaded" — and the brief's own framing of the failure case (a fix that
"can be on disk and not in the process ringing it") is explicitly about the working tree,
not a ref. A collector mid-development-loop, running against a checkout where someone is
iterating on `status.py` before committing, would stay stale under this definition exactly
as it does today.

**mtime has one gap worth naming and dismissing.** A `touch`-only edit with unchanged
content produces a false restart (harmless — restart is cheap, §5) and, in the other
direction, a save tool that preserves an old mtime (rare, and not a pattern anything in
this codebase's own edit workflow does) could produce a false negative. Content hashing
has neither failure mode.

**Recommendation: content hash of the watched files, computed fresh each check and
compared against the hash taken at process start — the same technique `store.py` already
uses for `_SCHEMA_HASH`** (`store.py:258`, `hashlib.sha256(SCHEMA.encode()).hexdigest()[:16]`,
compared against a stored value at `store.py:310`/`:448`). This is not a novel mechanism
being introduced; it is the same "hash a source string, compare to what was true at some
earlier point" pattern already load-bearing elsewhere in this codebase, applied to `.py`
source instead of a schema string.

**The single reason that decides it, over mtime:** the failure case named in the brief is
specifically an *uncommitted edit on disk*, and content hashing is the only candidate with
no gap against that case at negligible extra cost — mtime is marginally cheaper but trades
away exactly the guarantee the brief says matters, for a saving too small to matter (both
are well under 1% of a 24ms tick; see §1's own measured cost of the *existing* per-collector
`git rev-parse`, 12.3ms, for scale).

**Which files to hash — wider than the prior audit scoped.** `audit/phase3-scope.md`
named `collector.py` and `panel.py`. §1 above shows the actual incident's stale logic
lived in `status.py` (the `ringable` predicate `collector.py` calls but does not define).
Hand-maintaining an exact import-graph file list (`collector.py`, `panel.py`, `status.py`,
`store.py`, `herdr.py`, `config.py`, ...) is a list that silently rots the next time a fix
lands in a file nobody thought to add. **Recommend hashing every `.py` file under
`switchboard/`** (`find switchboard -name '*.py'`, sorted for a stable order, concatenated
and hashed) rather than a hand-picked subset — it is the same cost class (the whole
package is ~14k lines / under 1MB, per `wc -l switchboard/*.py`) and removes the
maintenance hazard entirely. If Andrew wants the narrower, cheaper scope instead, the
tradeoff is exactly that maintenance risk versus a marginally smaller hash input — not a
different mechanism.

**Check frequency need not be every tick.** The pass condition is "the next tick behaves
per the new code," not "detected within 2 seconds" — nothing in BUILD-PLAN or the incident
narrative needs sub-doorbell-latency detection. Recommend gating the check the same way
`ring_doorbell` gates itself off `DOORBELL_GAP` (a floor, not every tick) at something on
the order of 30-60s, which amortizes even the negligible per-check cost further and keeps
the change small: one more `State` field (`last_signature_check`), one more constant
alongside `DOORBELL_GAP`.

### 3.1 — the per-worktree question, separated out

The brief also asks about scoping "per worktree," and the honest answer is that it is a
**different question from staleness**, not a fourth candidate for the same slot. `Paths`
is keyed on `git_common_dir` (§1), so today exactly one collector exists per repo no matter
how many worktrees have panels open, and that collector's code is whichever checkout's
board pane happened to win the spawn race (`panel.ensure_collector`'s `PYTHONPATH` names
the *spawning renderer's* `Path(__file__).resolve().parent.parent`, `panel.py:456`).
A content-hash check, scoped to `Path(__file__).resolve().parent` (**this collector
process's own checkout**, not a canonical or configured one), answers "has my own checkout
drifted from what I loaded" correctly regardless of which worktree that turns out to be —
it does **not**, and should not, answer "has some *other* worktree of this repo changed,"
because that worktree's files are genuinely different code, not the same code gone stale.
Recommend leaving the one-collector-per-repo election exactly as it is; nothing in the
reported incident needed per-worktree collectors, and building that would be materially
larger (one lock/snapshot/demand triple per worktree instead of per repo, touching
`Paths.resolve()` and every renderer that calls it) for a distinction the brief's own
incident does not turn on.

---

## 4. Blast radius

Files a fix touches, using the recommended shape (content hash, checked on a
`DOORBELL_GAP`-style floor, exit via the existing clean-stop path):

- **`switchboard/collector.py`** — the only file with real logic changes:
  - `State` (`:99-131`): one new field, e.g. `source_signature: Optional[str] = None`,
    plus a `last_signature_check: Optional[float] = None` if the check is rate-limited.
  - a new small function, e.g. `source_signature() -> str`, sibling to `doorbell_sb()` —
    same file, same shape of helper.
  - `tick()` (`:283-309`) or `run()`'s loop (`:346-353`): one comparison against the value
    captured at start of `run()`, and — on mismatch — the same exit path
    `_nobody_is_looking()` already uses (return `True`-shaped signal that ends the loop,
    letting `run()`'s existing `finally: panel.release(fd)` do the rest). Reusing that path
    is the point: no new shutdown code, just a second reason to take the one that exists.
  - `run()` (`:312-356`): capture the initial signature once, near where `db_path` is
    resolved (`:334-343`), so it is paid once per process like the `git rev-parse` the
    module docstring already describes.

- **`switchboard/panel.py`** — likely **no changes**, if the check lives entirely inside
  the collector's own loop (self-check-and-exit) rather than a renderer comparing against
  it and signalling the pid, which was the shape `audit/phase3-scope.md` sketched. Self-
  check is simpler: it needs no new IPC, no signal-sending code in `ensure_collector`, and
  no renderer-side polling of "what checkout am I running vs. what did the collector load."
  The existing takeover mechanism (a renderer starts a new one whenever the lock is free,
  `panel.py:432-455`) already handles "there is no collector" identically whether the old
  one exited because nobody was looking or because its code changed — no new code needed
  on the renderer side either way.

- **`defaults/settings.toml`** — one new setting if the check interval is made tunable
  (matching `DOORBELL_GAP`'s own precedent of being a constant in `collector.py`, *not*
  a setting — `collector.py:82-91`'s comment says as much: "not a tunable"). Recommend the
  same treatment: a constant in `collector.py`, not a new `[panel]` key.

- **`tests/test_panel.py`** — new tests in the `CollectorLifecycle` class (§2, Test A).

**Collision with 3.5 (the reconciler).** `audit/phase3-scope.md` already flags this and it
is confirmed here: 3.5's natural home is the same loop, `collector.tick()`
(`collector.py:283-309`) or `run()`'s while-loop (`:346-353`), gaining a second
`DOORBELL_GAP`-shaped trigger alongside `ring_doorbell`. If 3.7 lands first, 3.5 is adding
a third gated call beside two existing ones (`ring_doorbell`, and 3.7's new signature
check) in the same function — straightforward, not a real collision, but real enough that
one person touching `collector.py` for both, or landing 3.7 first and rebasing 3.5 on top,
avoids two people editing `run()`'s loop body and `State`'s field list in parallel. This
matches `audit/phase3-scope.md`'s own recommended order (3.7 before 3.5) and there is
nothing here that changes that recommendation.

---

## 5. Restart safety

**The exit path this recommends is not new** — it is `_nobody_is_looking`'s existing
clean-stop path, reused for a second reason. That matters because the safety properties
are already proven by the current code, not something a fix has to newly establish:

- **The flock releases automatically.** It is held by an fd for the process's life
  (`collector.py:312-325`); any process exit — clean return, signal, or `kill -9` — drops
  it at the kernel level. There is no "stale lock" state to design around (`panel.py:49-51`'s
  own docstring makes this the explicit reason the design holds the lock for the whole
  process rather than per-tick).
- **The collector never itself writes to the store.** Every write happens in a spawned
  `sb` subprocess (`collector.py:47-55`'s module docstring: "it does NOT call
  `flush_pending` itself... it spawns `sb` instead"). So there is no half-written row, no
  open transaction, and no partial write to roll back when the collector process ends —
  the store is exactly as consistent after an abrupt collector exit as before one.
- **An in-flight doorbell (`sb flush`) is not lost.** `_run_doorbell` (`collector.py:270-280`)
  runs in a daemon thread, but the actual work is a **separate OS process**
  (`subprocess.run([sb, "flush"], ...)`, `:275-276`) — killing or exiting the *parent*
  Python process does not kill an already-spawned child process; it becomes an orphan
  re-parented to init and runs to completion on its own. The only thing genuinely lost if
  the collector exits mid-flush is the bookkeeping (`state.doorbell_error`, `:277-280`) —
  which was only ever going to be published in a snapshot that a fresh collector overwrites
  within seconds anyway, so losing it is invisible.
- **What actually is lost, briefly:** the freshness of the published snapshot, for the gap
  between this collector's exit and a renderer's next `ensure_collector` call. Bounded by
  `Supervisor`'s `spawn_cooldown` (5.0s, `panel.py:484-497`) plus however long a renderer
  takes to draw again — worst case a few seconds where panels show a snapshot that is
  correctly marked stale (`Reading.stale`, `panel.py:220-224`, and its `note` property
  explains why, `:226-244`) rather than silently wrong. This is strictly better than
  today's failure mode (hours of a *fresh-looking, non-stale* but logically wrong
  snapshot, because `collected_at` keeps advancing even though the logic deciding
  `ringable` is old).
- **The one thing to get right in the implementation, not a safety gap so much as a
  correctness detail:** the check-and-exit must happen at a tick *boundary* — after
  `tick()` has published — not mid-tick, so a renderer never reads a half-updated envelope.
  `run()`'s loop already only evaluates `_nobody_is_looking()` right after `tick()` returns
  (`collector.py:347-352`); placing the signature check in the same spot inherits this for
  free.

**Net:** nothing new needs to be built for restart safety. The "notice and exit" shape the
prior audit sketched composes cleanly with the shutdown path that already exists and is
already tested (`tests/test_panel.py::test_the_lock_is_held_for_the_whole_run_and_released_after`,
`::test_it_retires_when_no_panel_has_looked_for_a_while`) — the fix is a second condition
feeding the same exit, not a new kind of exit.

---

## What surprised me

- **The stale logic in the reported incident lives in `status.py`, not `collector.py` or
  `panel.py`.** `ring_doorbell` only decides *whether to spawn* `sb flush` based on
  `AgentStatus.ringable`, defined in `status.py` and imported once at collector start;
  the doorbell subprocess itself always runs current code. `audit/phase3-scope.md`'s file
  list for a fix (`collector.py`, `panel.py`) is therefore narrower than what actually
  needs to be covered by "did my code change" — see §3's recommendation to hash the whole
  `switchboard/` package rather than a hand-picked file list, specifically to avoid this
  kind of gap recurring the next time a fix lands somewhere collector.py doesn't
  obviously touch.
- **No renderer-side change looks necessary.** The prior audit's sketch had a renderer
  compare a stamped version and signal the collector's pid to kill it. A self-check inside
  the collector's own loop, exiting through the same path `_nobody_is_looking` already
  uses, needs no new code in `panel.py` at all — the existing takeover mechanism (any
  renderer starts a fresh one when the lock is free) already covers "the old one is gone,"
  whatever the reason.
- **Restart safety was already established by the existing design**, not something this
  fix has to newly provide — the collector never writes to the store itself and an
  in-flight doorbell is a real subprocess that outlives its parent's exit. I did not find
  a in-flight-work-loss scenario worth flagging as a risk.
- **No bug report existed for this incident** (confirmed by listing
  `~/.local/state/switchboard/plugins/report-bug/`, most recent entry before this session
  dated 2026-08-09) — filed during this pass:
  `~/.local/state/switchboard/plugins/report-bug/2026-08-11-014308-the-collector-runs-stale-pre-fix-code.md`.
