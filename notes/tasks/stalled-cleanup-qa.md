# Task: independently verify the stalled-cleanup fix

**Verify, do not fix.** Change no source file, write no commit. If you find something
broken, report it — do not repair it.

## What you are verifying

Commit `65dcd53` on branch `stalled-agent-cleanup` (`switchboard/broker.py`,
`tests/test_broker.py`). The implementer's claims are in
`notes/worker-58-stalled-cleanup-report.md`; the task it was built from is
`notes/tasks/stalled-cleanup-fix.md`; a scout's map of the machinery is
`notes/researcher-45-stalled-agent-lifecycle.md`.

Treat every one of those documents as a **claim to be checked**, not as evidence.
`DESIGN-TRUTH.md` is the only trusted document in this repo. Do not reproduce the
implementer's own experiment from its description — read what the code does now, then
design your own run.

## The claims, each of which needs its own proof

1. A row switchboard calls `stalled` is closed by a **bare `sb cleanup` sweep**, with no
   `--force`, where before the change it was refused.
2. An agent **named outright** is also closed when it is merely `turn_doubted` (the
   earlier, undebounced doubt) — and a bare sweep does **not** take that same row.
3. A **genuinely mid-turn** agent is still refused, by name and by sweep.
4. The refusal for a **named** agent tells the caller `--force` is the way through; the
   **sweep** refusal does not (because `--force` is illegal on a sweep — check that it
   still is).
5. Every other gate still applies on top: self, already-closed, **live descendants**
   (which nothing should lift, not even `--force`), gone-but-unconfirmed, and **unread
   mail** — a stalled row holding unread mail must still be refused.
6. The suite is green. Run it: `/Users/andrew/anaconda3/bin/python -m pytest tests`
   (the pythons on PATH here look broken when they are not). Report the count, and
   whether the four new tests actually fail against the pre-change `broker.py` — a test
   that passes either way pins nothing.

## How to run it

Live proof in an isolated instance is the primary evidence, and what this is judged on.

- `git clone` this repo into a scratch directory; a clone gets its own store via git's
  common dir. Check out the branch there and drive **that clone's own `./bin/sb`**.
- **Never run a clone's `sb` from outside the clone** — that silently touches the live
  store.
- Agents you spawn in the clone are invisible to the live fleet's store but **not** to
  herdr, which is machine-global: they appear in Andrew's spaces UI, so tear down
  everything you create. Never an unscoped `pkill` — kill by verified pid after checking
  each process's cwd. The live fleet's collector must be left alone.
- Prove each claim in the smallest run that can tell fixed from broken. To show a claim is
  a *change*, run the same shape against `87572c1`'s `broker.py` as well.
- No endurance testing.

## Known-unproven, and what I want from you

The implementer says claim 5's stalled-plus-unread-mail case is pinned by **unit test
only** — it could not build it live, because a stalled agent whose session is still alive
gets rung, wakes, and reads the mail. Do not kill a Claude process to force it. Instead
tell me whether the unit test exercises the real code path or a shape that cannot occur,
and say plainly what remains unproven either way. A sentence naming what is unproven is
worth more than a test that cannot fail the way production fails.

The implementer also filed a separate bug it did not fix (`cleanup_refused` resets the
refused agent's idle clock, suppressing the stale-turn repair — report id
`2026-08-15-111506`). Confirm or refute that it is real, since it bears directly on
whether these rows ever reach `stalled` in the first place. Do not fix it.

## Report

`sb done` with a verdict per claim — proved / refuted / unproven and why — the suite
result, and one plain sentence on whether this is safe to land. Detail in a file under
`notes/`; give me the path, do not commit it.
