# Review pass — 2026-08-07

Whole-repo pass for consistency, redundancy, doc drift and open bugs.

> **Reading this after the fact (checked against `main` @ `71bec8a`, 2026-08-12).** This is
> a dated record of one pass and is not edited to match the code. Four things in it have
> since been overtaken, and they recur throughout:
>
> - **`agent prompt` queues; it does not interleave.** The "interleaves" claim here and the
>   deferred-doorbell reasoning built on it were re-measured and retracted — see
>   `Herdr.prompt`'s docstring. Holding a ring is now the `--when-idle` mode, one of three,
>   rather than what every message does.
> - **`sb ask`, `sb wait` and `sb interrupt` (the verb) are deleted**, along with the human
>   inbox. Every behaviour change below that names one describes code that is gone;
>   `sb block` notifies and writes no mailbox row, because the human has no mailbox.
> - **`--all-idle`/`--include-kept` are gone**, with the rest of the cleanup disposition
>   flags.
> - **"Nothing enforces `sb done`" is closed.** The `Stop` hook it calls still-unbuilt was
>   built (`switchboard/hooks.py`, `bin/sb-stop-hook`), and a reconciler pings an agent that
>   stayed silent anyway.

**Suite:** 507 tests → **569**, green. The one test that was failing intermittently
(`test_concurrent_openers_all_land_in_the_one_workspace`) was reproduced at **2 failures
in 25 runs** before the fix and is **0 in 60** after it. No test was deleted.

**Behaviour changed in eight places.** Each is listed under "Behaviour changes" below with
what it used to do. Everything else preserves behaviour.

---

## The three that mattered

### 1. `Broker.flush_pending` was never called by anything

Not in `BUGS.md`, not in `QA-FINDINGS.md`, and the worst thing in the tree. Its own
docstring said *"Called at the start of every `sb` command"*. Nothing called it.

The deferred doorbell that landed just before this review is correct and is the right
design: `agent prompt` **interleaves** — it injects into the turn the agent is in the
middle of rather than queueing after it — so `_ring` holds the doorbell back while a target
is mid-turn, and `flush_pending` is what rings once it is free. With nothing calling it:

- `sb tell` to a working agent wrote a durable row that was **never announced, ever**. Not
  latency — permanent liveness loss with no recovery path.
- `sb ask` to a working agent blocked for its **full fifteen minutes** on a question the
  target had never been told about.
- `sb done`'s poke to a working parent vanished the same way, so a lazy parent never woke.

Fixed in two places, because one is not enough. `cli.main` flushes at the start of every
command — that is the trigger the docstring already promised, and in a live session
something runs `sb` constantly. But nothing else runs while `ask` blocks, so `ask` also
flushes on every pass of its own wait loop, with the who-is-busy cache invalidated (a
per-process cache is fine inside a short command and wrong inside a fifteen-minute one).

When an events daemon exists it replaces the *trigger*, not the model.

### 2. The `_adopt` race — fixed by inverting the order, not by catching the error

`BUGS.md` suggested catching `IntegrityError` in `_adopt` and re-reading. That would have
silenced the loud face and left the quiet one, because the two faces are different races:

- **`IntegrityError`** — two openers both `_adopt` the same live agent.
- **`created == 0`** — `_adopt` racing `delegate`. Thread A started the herdr agent and
  *then* tried to write its row; B had already adopted the agent A had just started, so A
  caught the IntegrityError, concluded it had lost, and reported `created=False`. The agent
  existed and nobody claimed to have made it.

The defect is the **order**: `delegate` spawned first and recorded second, so the store —
the only thing concurrent openers share — was consulted *after* the decision it was
supposed to arbitrate.

- `store.claim_agent` is `INSERT OR IGNORE` returning whether this process got the row. The
  PRIMARY KEY on `agents.name` is the arbiter, which is what a PRIMARY KEY is for.
- `Broker.delegate` claims the name **before** `agent start`. A spawn that then fails
  leaves the row behind as a husk (`failed`, no pane, no session) plus a `spawn_failed`
  event, rather than deleting it and throwing away the only evidence the attempt happened;
  the claim carves that shape out, so a failed spawn still cannot hold a name hostage.
- `_adopt` claims instead of inserting and re-reads on a loss.
- `_spawn_lead` now distinguishes **three** shapes of prior row rather than two: a session
  id means restore; a pane and no session means another opener is mid-spawn into this name,
  so join it; neither means a husk, so replace it. The middle case did not exist before and
  is exactly what a claim creates.

Two things fell out. `sb delegate --name <existing>` used to raise a bare
`sqlite3.IntegrityError` through the CLI as a **traceback**; it is now `AgentNameTaken`, a
ValueError the CLI already handles. And losers no longer create a tab at all, so a
contested workspace cannot fill with dead shells — there is nothing to clean up because
nothing is made.

### 3. `Herdr.wait` — both bugs fixed in the adapter, not around it

The workarounds in `status.py` were correct and were in the wrong file. Anything that
called `Herdr.wait` without having read `BUGS.md` got a method whose **default argument was
unusable** (`--until idle,blocked` is refused outright, so every call failed instantly and
nothing ever waited) and which span at ~100% of a core when the stale-seq guard rejected an
answer herdr returned instantly.

- `until` is now a single `str` defaulting to `IDLE`, validated before any subprocess runs.
  The signature matches what the CLI underneath can actually do, instead of offering a set
  and joining it into something always refused.
- A rejected answer sleeps `timeouts.agent_wait_backoff` before re-asking, clamped so it
  never sleeps past the deadline.
- `status._next_transition` stays and returns a `str`. It is still the better mechanism —
  asking for the state the agent is *not* in makes every wait a real block — so the backoff
  is the adapter refusing to burn a core for a caller that has not been that careful.

**The test that was missing now exists** and asserts on the argv. That absence is the whole
reason a public method's default argument could be unusable.

---

## Bugs — every entry verified

`BUGS.md` and `QA-FINDINGS.md` now carry a **STATUS** line per entry with the detail. There
is no git history in this tree (no commits), so fixes are cited at file and function level
rather than by commit.

| Source | Entry | Disposition |
|---|---|---|
| BUGS 1 | `_adopt` race | **FIXED** — 0/60, was 2/25 |
| BUGS 2 | `--until idle,blocked` | **FIXED** in the adapter |
| BUGS 3 | `Herdr.wait` 100% CPU | **FIXED** in the adapter |
| BUGS 4 | schema-change deadlock | **FIXED** — and the escape hatch now exists (below) |
| BUGS 5 | `sb wait` returns early | **NOT REPRODUCIBLE** — property pinned by two tests |
| QA B1 | `restore` destroys identity | already fixed |
| QA B2 | `block` is a one-way door | already fixed; extended (below) |
| QA B3 | `tell` reports false success | **FIXED** |
| QA B4 | `ask` does not validate targets | already fixed; extended (below) |
| QA B5 | answers delivered three times | **FIXED** |
| QA B6 | `--all-idle` does not close idle agents | **FIXED as a naming bug** — see the disagreement below |
| QA B7 | no way to clean up a stuck agent | **FIXED** — `sb cleanup <name> --force` |
| QA B8 | `restore` leaks a pane | **FIXED** |
| QA B9 | `pane_id` goes stale after cleanup | **FIXED** |
| QA B10 | `--json` is global-only | **FIXED** |
| QA B11 | `sb status` shows store state | already fixed (it grew into `status.py`) |

Three notes worth pulling out of those files.

**BUGS 4's escape hatch did not exist.** `store._reset`'s error told the human to run
`sb doctor --reset-store --force`, and **`sb doctor` had no such flags** — the one way out
of an unrecoverable deadlock was a command that would exit 2 on unrecognised arguments. An
error naming a command that does not exist is worse than one naming none, because it costs
the reader the time to try it. Both flags added.

**BUGS 5 I could not reproduce, and I am not calling it fixed.** `--for done` is satisfied
by exactly one thing — the store saying `done` — and every other exit from `wait_for`
returns `ok=False`. Both theories in the entry are ruled out by reading the code (herdr has
no `done` state at all, so `--for done` maps to no herdr state to be "already satisfied").
Most likely the two commands in the report were not the same instant, or it predates the
current `wait_for`; there is no git history to check that against, so it stays a guess and
is labelled one. What was missing was a test, and two now exist.

**QA B6 is a disagreement, not an omission.** The finding asked for `--all-idle` to close
anything herdr reports idle. It should not: herdr `idle` means "no turn is running *right
now*", which is equally true of an agent between two turns of a job it is half-way through,
and a sweep names no target so nobody has confirmed anything about any particular agent.
The flag never closed by idleness — what it does is lift the role's `keep` disposition — so
it is now spelled `--include-kept` with `--all-idle` as a permanent alias on the same
`dest`. The want underneath ("this one is stuck, close it") is B7's, and that is where it
is answered.

---

## Redundancy — what collapsed and what deliberately did not

The brief named three candidate merges. Two are genuinely one idea underneath and now share
a code path; none of the three verb pairs was merged, and the reasons are now in
`broker.py`'s module docstring so they are not re-argued.

**`block` vs `ask human` — two code paths that had drifted; now one mechanism, two verbs.**
Both are "surface to the human", both go through `_surface`. But `ask` wrote a mailbox row
and `block` did not, so a block reached the human as a desktop notification only — gone the
moment it was dismissed — and `sb inbox` was silent about blocks while `sb status` listed
them. `block` now writes to the human's mailbox too. What is *not* merged is the waiting:
`ask` holds the agent's turn open, `block` ends it and is restarted by the doorbell. Given
C10 the second is usually the right shape, which is why both exist. (Deliberately a `tell`
row and not an `ask` row — an answer to a pending `ask` now rings nobody, and a blocked
agent's turn has ended, so its reply **must** ring.)

**`tell` vs `interrupt` — not merged; they differ in mechanism, not degree.** `tell` writes
a message and rings a payload-free doorbell that is *held back* while the target is
mid-turn. `interrupt` cancels the turn with `esc` and puts the instruction itself on the
wire. Deferring an interrupt defeats it; interrupting on every `tell` is what the deferral
exists to prevent. One real gap was closed: `interrupt` wrote no row at all, so the
instruction existed only in a pane. It now records the message (delivered and read, since
it arrived inline), so it is durable and shows in `sb inspect` (C7).

**`wait` vs a deferred `ask` — not merged, and `wait` is not `ask --when-idle`.** Deferred
delivery already exists and is the default for *every* message. What `wait` waits for is a
**state**, on behalf of a caller that is not an agent — no turn to end, no doorbell to be
rung on. `sb wait w1 && deploy` in a shell script has no other shape available.

**Dead code removed.**

| Removed | Why |
|---|---|
| `Broker._spawn_top`, `Broker._resume_top` | line-for-line duplicates of the two halves of `_top`; unreachable |
| `Broker.status` | unreachable, and it returned store rows *alone* — the readout that reports a stalled agent as busy all day. `sb status` goes to `status.py`, which joins |
| `Broker.is_worktree` | unreachable |
| `Herdr.pane_ids` | unreachable; docstring cited a use ("tell a closed board pane from a live one") that does not exist |
| `Herdr.close_workspace`, `Herdr.remove_worktree` | unreachable, untested |
| `Herdr.split_pane` | unreachable once `open_beside` went |
| `board.open_beside` | unreachable, **and its docstring and `scripts/README.md` both described it as what `sb start` does**, which was never true. Gone rather than wired up: auto-opening a board is a decision about a human's screen |
| `display.split_ratio` | its last reader went with the above |
| duplicated `summary_line` / `_clip` in `board.py` | two hand-maintained copies of "how many agents, and how many are trouble" is how two readouts of one store come to disagree in front of you. Now `status.summary_line` / `status.clip` |
| `from .broker import HUMAN` inside `status._subtree` | the module reads it from `[vocabulary]` at the top now; two spellings of one constant |
| unused imports in `cli.py`, `broker.py`, `status.py` | — |

**`switchboard/board.py` earns its place.** It is a working human surface with a real entry
point (`python3 -m switchboard.board`), it is what `PRINCIPLES.md` C14 calls the product,
and `scripts/06-board.py` is its superseded prototype rather than the other way round. What
did not earn its place was the dead `open_beside` and the false claim around it. It had
**zero tests** for 430 lines, which matters here more than elsewhere: a misdrawn row still
looks like a row, and the click that follows focuses a different agent than the one under
the cursor — silently, and indistinguishably from a correct click. `tests/test_board.py`
now pins decode → layout → `agent_at`, including that no line may ever wrap.

**Kept despite having no caller:** `store.agent_by_session`. It is the reverse of what
`_claim_session` records and the schema indexes it. Its docstring was the problem — it said
"Who am I?", which stopped being true when identity moved to `HERDR_PANE_ID` — and that is
fixed.

---

## Consistency

- **`--json` is now genuinely per-command**, on either side of the subcommand, via a parent
  parser every subcommand inherits, with `default=argparse.SUPPRESS` so a per-command flag
  can only ever *set* the value and never silently undo `sb --json <cmd>`. The test builds
  its check from the parser's own subcommand list and asserts that list is what it expects,
  so a verb added later cannot quietly miss the flag.
- **One error shape.** `str(KeyError)` adds quotes and `str(ValueError)` does not, so half
  the errors this CLI printed came out quoted (`sb: 'no such agent: w1'`) and half did not,
  for no reason a reader could see. Both are "you named something that is not there".
- **One way to name an agent.** `--agent` on `sb workspace new` was the odd one out against
  `--name` on `start` and `delegate`; `--name` is now the spelling and `--agent` a
  permanent alias on the same `dest`, exactly as `sb status --live` is.
- **One `FINISHED`.** `broker.cleanup` had `("done", "failed")` inline while the readouts
  read it from `[states]`; "finished" cannot be allowed to mean two things in two files.
- **The protocol gained two clauses**, both from observed live failures rather than taste.
  Agents were treating mail as untrusted suggestion and stalling (QA's protocol
  observation), so parent authority is stated. And the protocol never mentioned `sb block`
  at all — it sent agents to `sb ask human`, which holds a pane for fifteen minutes waiting
  on a human who may be asleep.

---

## Doc drift

`BUGS.md` and `QA-FINDINGS.md` gained per-entry status; nothing in them was edited or
deleted, because the original observation is the record.

`POC.md` and `PLAN.md` were written as the design evolved and are now annotated rather than
rewritten — wrong turns marked **RETRACTED** with what replaced them and why:

- **`wf` → `sb`** throughout, noted once at the top of each rather than at every mention.
- **`wf reply` and `wf who` never existed** and should not; both marked with the reasoning.
- **Identity is the PANE, not the session** (`POC.md` said session id). The
  "don't mint, don't inject" half stands; the key changed, because the session id only
  lands once an agent has made a call and a first-call lookup would resolve to `human`.
- **"No migrations: drop, or refuse"** — retracted in practice, with the deadlock it caused.
- **The M1 schema block** now has a table of every difference between it and what shipped,
  with why: `name` as PRIMARY KEY, no `reply` message kind, `delivered_at`, and the rest.
- **M2 decision 7 ("one agent per pane")** was already contradicted by finding #15 further
  down the same file; the decision itself is now marked.
- **`agent wait --until`, the spawn signature, cleanup flags** brought in line.
- **"Open for review" 1–5** each answered where they were answered, and #5 says plainly
  which half is still open.
- **PLAN's D1** (recommended TypeScript) — what shipped is stdlib Python; every premise of
  the recommendation is addressed. **D2** was never resolved and was sidestepped: `sb done`
  is the report, so F16 stopped mattering, but nothing *enforces* it and that is C6's
  problem, noted at C6 in `PRINCIPLES.md` too.
- `PRINCIPLES.md` gained two short "as built" notes, at **C6** (nothing enforces reporting;
  detection covers for it, and that is not a substitute) and **C10** (no daemon, so no event
  subscriptions; the polling that replaces them is the zero-token kind — and `Herdr.wait`
  was violating the principle outright).
- `scripts/README.md` described a `04-cleanup.sh` that was never written and a board that
  `sb start` opens, which it never did; `wf-shim.sh` was in the directory and not in the
  table.
- Code docstrings that contradicted verified findings: `Herdr.prompt` still said prompts
  **queue** against a busy agent (retracted by `POC.md` finding #9 — they interleave, which
  is the whole reason the doorbell is deferred); `output.py` documented a `Broker.output`
  that does not exist; `cli.py` claimed every command took `--json`.

---

## Behaviour changes

Preserving behaviour was the default; these are the exceptions.

1. **A deferred doorbell now actually rings.** Previously it never did (see above).
2. **An answer to a pending `ask` rings nobody**, and is marked read and delivered. It used
   to arrive three ways — as the return value, as an unread row, and as a prompt injected
   into the asker's turn — costing the asker a turn per ask, one per target on a fan-out.
   *Accepted cost:* an asker whose `ask` had already timed out now gets the answer with no
   announcement. It is still in the store and in `sb log`. The alternative is paying a turn
   on every answer forever.
3. **`sb block` writes to the human's mailbox** as well as notifying.
4. **`sb interrupt` records its message** (delivered and read).
5. **`sb ask` stops waiting on a target that has reached `done` or `failed`** rather than
   sitting out the timeout — that is something the agent recorded about itself, so the
   answer is provably not coming. Deliberately store-only: an agent missing from `herdr
   agent list` looks the same whether it died or herdr hiccupped.
6. **`sb cleanup` takes names and `--force`**, and `--all-idle` is now `--include-kept`
   (alias kept). `--force` refuses to run without names.
7. **`sb cleanup` clears `pane_id`** on the rows it closes.
8. **`sb restore` refuses a live agent** instead of failing three spawn attempts and leaving
   an orphan pane behind.

`Herdr.wait`'s signature changed (`until: Sequence[str]` → `until: str`). Not listed above
because the old form could not be called successfully.

---

## Still open

- **A schema change that cannot be applied in place still rebuilds the store**, and that
  is now the only shape left: nullable columns and whole nullable tables are added and
  backfilled, so only a gap no existing row can be given (a `NOT NULL` column with no
  literal default) gets there. It is no longer a hard stop — under a live fleet the
  rebuild is deferred and the old store keeps serving — but the "operational state is
  disposable" assumption still does not survive contact with long-lived agents, because
  when the rebuild does run it drops everything.
- **Nothing enforces `sb done`** (C6, PLAN D2). Detection covers for it; a `Stop` hook is
  still the right answer and is still unbuilt.
- **A child that dies without recording anything** records nothing for a blocked `ask` to
  read. `ask` no longer sits out the whole timeout for it: it counts *consecutive*
  absences from `herdr agent list` and gives up after `timeouts.gone_grace`. That grace is
  300 s and is floored at `status.SPAWN_GRACE` by an assertion, because anything shorter
  writes off children that have done nothing but start slowly. `sb status` still names the
  case as GONE, and it is still a wait rather than a signal.
- **BUGS 5** — see above. Not reproducible, not closed.
- **`herdr` is a real dependency of two tests' environment** only in the sense that
  `sb doctor` shells out; the suite itself runs with no herdr and spawns nothing.

---

## Note on side effects

One smoke test of `sb tell` against a seeded row in a scratch repo fell through to the pane
fallback and typed `You have mail. Run: sb inbox` into live herdr pane `w1:p1`, followed by
Enter. That is one stray line in whatever was running there. Nothing else in this pass
touched a live agent, spawned anything, or wrote outside the repo and the scratch directory.
