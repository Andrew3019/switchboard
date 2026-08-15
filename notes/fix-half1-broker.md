# Half 1 — a live agent is no longer stamped GONE because herdr lagged

Commit `24d09b9`, files `switchboard/broker.py` and `tests/test_broker.py` only.

## The change

- `Broker._spawn` takes `sent = time.time()` immediately before `self.h.deliver(...)`.
  That is within a hair of `deliver`'s own first-attempt `sent`, and well inside
  `task_arrived`'s 5 s clock slop.
- `Broker._took_a_turn` now takes `task`, `cwd` and `since` (keyword, all optional) and
  asks `output.task_arrived(cwd, task, since=since)` **first**, before the store row and
  before the herdr probe. The two old checks are untouched.
- `switchboard/output.py` and `switchboard/herdr.py` unchanged.

## Soft or hard, and why

A transcript hit was put on the **soft** side — the same side the existing "herdr says
working" check sits on. So it logs `task_unconfirmed`, sets `delivery_note`, and returns
the name; it never turns a spawn into an unqualified success.

Why: the task said not to move that line, and the honest statement is still "no *send*
could be confirmed inside the delivery window". The transcript read is a late look at the
same evidence, taken after `deliver` gave up, so a note pointing the caller at
`sb inspect` costs nothing and a silent success would hide that delivery timed out. It
also keeps the number of outcomes at two.

The note now reads: `… But the task is in its own transcript, it just landed late, so it
most likely took the task and nothing has been closed or respawned.`

## Automated proof

`tests/test_broker.py`:

- `test_a_task_that_landed_just_too_late_is_not_a_failed_spawn` — a fake herdr whose
  `deliver` writes a real transcript file (real dir, faked `HOME`, the pattern already in
  `test_output.py` and in this file's `…_confirmed_against_the_childs_own_transcript`) and
  then raises. Store row not done/blocked, herdr not working. Asserts no
  `TaskUndelivered`, row still `working`, `task_unconfirmed` logged and not
  `task_undelivered`. **Verified to fail on `24d09b9^`** and pass with the change.
- `test_a_transcript_that_holds_nothing_still_fails_the_spawn` — the other side of the
  line: a real transcript directory with no task in it is still a lost task.

Nothing was added to `FakeHerdrAPI` beyond what its existing `deliver` hook allows.

Whole suite: `1235 passed` (`/Users/andrew/anaconda3/bin/python -m pytest tests`). The run
included another agent's in-progress `switchboard/herdr.py` edits, which were also green.

## Live proof — before and after, isolated clone

Clone of this worktree in a scratch dir, driven by its own `./bin/sb`. Timings starved via
`SWITCHBOARD_DEFAULTS` pointed at a copy of `defaults/` (the repo's own
`defaults/settings.toml` was not touched; note that `config.setting` is called at import
with `repo=None`, so a `<repo>/.switchboard/settings.toml` override would *not* have
reached these constants).

Starved settings: `deliver_ms = 300`, `deliver_poll = 0.5`, `deliver_working_ms = 0`,
`deliver_attempts = 2`, `spawn_backoff = 8`.

Why that shape forces the race: send 1's 300 ms window closes before Claude Code flushes
its transcript (~1 s), and send 2 happens 8 s later, so send 2's own `since` floor
(`sent - 5 s`) is already *past* the record send 1 produced — `deliver` is blind to a
transcript it would otherwise have found. That is the same "proof exists, deliver cannot
see it" state the incident hit by luck of a poll gap.

Same task both sides: `Reply with the single word ok. Run no commands at all and do not
report done.` (chosen so the child is idle, not `working`, and never writes `done` — so
neither of the two old checks can answer).

| | before (`24d09b9^`) | after (`24d09b9`) |
|---|---|---|
| `sb delegate` exit | **1**, `task_undelivered` | **0** |
| store row | `failed` | `idle` (never stamped) |
| transcript on disk | yes — task text present twice | yes |
| agent | alive and had answered | alive and had answered |

Earlier runs at `deliver_ms = 200` failed on both sides — there the transcript genuinely
had not been written yet at check time, so the fix correctly did not rescue them.

Teardown: every agent closed (`sb cleanup <name> --force`), herdr shows none of them, the
clone and its forked worktrees under `~/.herdr/worktrees/sbclone/` deleted. No `pkill`.

## Noticed, not fixed (reported, not touched)

Two of the throwaway spawns (`brk1`, `brk2`) never produced a transcript directory at all
— the paste-without-submit mode, i.e. half 2's bug, reproduced live on HEAD in a cold
clone. That is `worker-55`'s file, untouched here.

## Unproven

- Whether the *original* incident's exact microstructure (proof landing in the final
  0.5 s poll gap) is reproducible on demand: it is not, with settings alone. The live run
  above forces the same end state — `deliver` raises while the proof sits on disk — by a
  different, deterministic route (the retry's `since` floor), not by winning that race.
- One live before/after pair, not a distribution. No endurance run, per house rules.
