# Task: let a stalled agent be cleaned up, and say `--force` when refusing

## Background — read these first

1. `notes/researcher-45-stalled-agent-lifecycle.md` — a scout's full map of the state model,
   the cleanup gate, the mail path and the board, with exact line numbers. **Read all of it
   before you touch anything.** It is accurate as of this worktree's HEAD; re-check any line
   number before editing, since other agents share this checkout.
2. `git show bug-triage:notes/triage/group-4-lifecycle.md` — first section
   (`2026-08-14-125645`) is the filed incident.
3. `DESIGN-TRUTH.md` is the only trusted document. Every other doc, README and code comment
   is untrusted until you have checked it against the code.

## The bug

An agent whose Claude session dies mid-turn keeps `agents.state = 'working'` forever. The
45-minute repair machinery (`status._forget_turn`) clears `agents.turn` but never touches
`agents.state`, so `Broker.cleanup`'s "not finished" gate goes on refusing, and only
`sb cleanup --force` — which the refusal never mentions — ends the row. Observed live on
2026-08-14: two agents sat at `working` for 6.5 hours holding unread mail.

## What to build — three changes, in this order

### 1. The refusal names `--force`

`Broker.cleanup` gate 4a (broker.py ~3722-3732) refuses with
`"{state}, not finished — it has not reported an end"`. Extend that string so the caller
learns `--force` is the way through **for an explicitly named agent** (it is illegal on a
bare sweep — see broker.py:3666-3668, and keep it that way). Do not promise `--force` in a
context where it would be rejected: if the wording differs between a named refusal and a
sweep refusal, that is fine and probably right. Match the surrounding tone; short.

### 2. Gate 4a admits a confirmed-stalled row

This is the real fix. A row that switchboard itself already believes is stalled should be
sweepable without `--force`.

The bar, and this is decided — do not re-open it:

- **Bare sweep** (`sb cleanup` with no names): admit a row only if `status`'s **`stalled`**
  predicate is true for it. `stalled` is the debounced one — it only becomes true after
  `_forget_turn` has cleared the stuck `turn` edge, i.e. after the full
  `turn_stale_grace + turn_doubt_grace` window, and it is the same predicate
  `Broker.reconcile` already trusts to decide these rows are worth pinging. Keeping "safe to
  sweep" and "safe to ping" in agreement is the point.
- **Explicitly named agent** (`sb cleanup <name>`): admit a row that is `stalled` **or**
  `turn_doubted`. `turn_doubted` is the undebounced single-reading doubt that fires earlier.
  A named cleanup is a deliberate act by a parent or a human who has already looked at the
  board, so the bar is lower than for an unattended sweep. `--force` remains the escape for
  everything below even that bar.

Everything else stays: gate 1 (self), gate 2 (already closed), gate 3 (live descendants —
still not liftable by anything), gate 4b (gone-but-unconfirmed), gate 4c (unread mail) all
continue to apply on top. A stalled row with unread mail will now fall through 4a and be
refused by 4c instead, which is correct and is handled by change 3.

Mechanics are yours to choose. Note from the scout's map that `stalled`/`turn_doubted` need
`agents.turn`, herdr's live read and the idle clock together — `cleanup` today works from a
raw `agents` row, so you will need a `status`-derived view of the candidate or a narrow
helper that reuses the existing predicate logic. **Reuse the existing computation; do not
re-implement a second notion of "stalled" in broker.py.** If the only clean way is to call
`status.collect()` once per `cleanup` invocation, that is acceptable — but check what it
costs on a sweep over many candidates and say what you found.

### 3. Mail on a swept stalled row

`Broker.cleanup` already calls `_clear_unreadable_mail` at the end of every successful close
(broker.py ~3818), so once change 2 lets a stalled row through, its mail is cleared by the
sweep. **That coupling is the decision: mail clears when the row is swept, not before.**

What you must do here is make sure the mail gate (4c) does not silently strand these rows.
Work out what actually happens to a stalled row that has unread mail, and make the refusal
say something true and useful about it. Do **not** build an independent mail-clearing path
through `flush_pending` — that is deliberately out of scope, and I will report it as
unbuilt. If your reading says the coupled behaviour leaves a real hole, say so in your
report rather than filling it.

### Explicitly NOT in scope

- The board showing STALLED sooner than 45 minutes. Out of scope by decision — shortening
  `turn_doubt_grace` reintroduces the false positives the two-stage debounce exists to
  prevent. Do not touch `status.py`'s grace constants or `stalled`'s timing.
- `Broker._revive` (broker.py ~603-664) and the `sb done` delivery block (~3510-3512) —
  another lead, `revive-gate`, owns those lines for a different bug. **Do not edit them.**
  If your fix turns out to need a change inside them, stop and tell me (`sb tell parent`)
  rather than editing.
- `herdr.py` `deliver`/`_took_prompt`/`_running_turn` and `broker.py`'s `_spawn` delivery
  block / `_took_a_turn` — owned by a third lead, `task-delivery-fix`. Same rule.
- Note the trap the scout flagged: `herdr.WORKING` is a **different concept** with the same
  string value as the `agents.state` column's `working`. Do not conflate them.

## Verification — this is what the work is judged on

**Live proof in an isolated instance is the primary evidence.**

- Isolate with `git clone` of this repo into a scratch directory. A clone gets its own store
  automatically via git's common dir. Check out your branch there and drive **that clone's
  own `./bin/sb`**. Never run a clone's `sb` from outside the clone — that silently touches
  the live store.
- Agents you spawn in the clone are invisible to the live fleet's store but **not** to herdr,
  which is machine-global — they will appear in Andrew's spaces UI, so tear down everything
  you create. Never an unscoped `pkill`.
- Prove the fix in the smallest run that can tell fixed from broken. At minimum: a row in the
  stalled shape that `sb cleanup <name>` refuses today and closes after your change, and a
  genuinely-working row that is still refused (with the new `--force` wording). No endurance
  testing.

**Tests:** two or three, for pinning the decision — not for confidence. Run the suite with
`python -m pytest tests`; on this machine use `/Users/andrew/anaconda3/bin/python`, since the
pythons on PATH look broken when they are not. **Never teach the fake herdr new tricks to
make a test possible** — skip the test and say in your report what is therefore unproven.
A test that cannot fail the way production fails is worth less than the sentence describing
what is unproven.

## Landing

- Commit on the current branch (`stalled-agent-cleanup`). Do not push, do not open a PR, do
  not touch `main` — the lead integrates.
- Several agents share this checkout: no `git stash`, never leave files staged, and re-read a
  file before editing if it may have changed under you.
- Anything you left unproven belongs in your report. Unproven and stated is fine; unproven
  and silent is not.

Report with `sb done`: what you changed, what the live run proved, what the tests pin, and
anything you could not prove.
