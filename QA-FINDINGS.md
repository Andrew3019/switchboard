# QA findings — live-agent exercise of `ask` / `block` / `restore` / `interrupt`

**Date:** 2026-08-07 · **Tester:** agent `qa-verbs` · **herdr:** 0.8.0 · **Claude Code:** v2.1.224

Scope: the CLI verbs that had unit tests but had never been run against live agents.
Every result below comes from real spawned agents, not mocks. Six throwaway fixtures were
spawned with `sb delegate` (`qa-ask1`, `qa-m1`, `qa-m2`, `qa-block`, `qa-int`).

> **Disposition, review pass 2026-08-07.** Every finding below was re-checked against the
> code as it now stands. Findings are not edited — the original observation is the record —
> and each carries a **STATUS** line naming where it was fixed. Nothing here was closed by
> re-running against live agents: this pass had no agents to spawn, so "fixed" means the
> code path was read, changed, and covered by a test, not that it was re-observed. The
> three findings that were fixed by someone else between the QA run and now are marked
> **already fixed** and say what fixed them.
>
> | | | |
> |---|---|---|
> | B1 `restore` identity | **already fixed** | `broker.py`, `restore()` clears `ended_at` |
> | B2 `block` one-way door | **already fixed** | `block()` reports `idle`, never `blocked` |
> | B3 `tell` false success | **fixed** | `tell` reports `undelivered`; retried by the doorbell flush |
> | B4 `ask` target validation | **already fixed** | `ask()` resolves targets first, raises `KeyError` |
> | B5 answers delivered 3× | **fixed** | an answer to a pending `ask` rings nobody |
> | B6 `--all-idle` misnamed | **fixed as a naming bug** | renamed `--include-kept`; see below |
> | B7 no way to clean up a stuck agent | **fixed** | `sb cleanup <name> --force` |
> | B8 `restore` leaks a pane | **fixed** | liveness checked before the tab; tab closed on failure |
> | B9 stale `pane_id` | **fixed** | `cleanup` nulls it |
> | B10 `--json` global-only | **fixed** | every subcommand, either side, pinned by a test |
> | B11 `sb status` shows store state | **already fixed** | `status.py` joins herdr; STALLED/GONE |
>
> The protocol observation at the bottom was also acted on.

> **Later still (checked against `main` @ `71bec8a`, 2026-08-12).** Much of what the
> disposition pass above describes as fixed has since been *removed* rather than kept, so
> those STATUS lines are a record of a fix, not a description of the code:
>
> - **`sb ask`, `sb interrupt` (the verb) and `sb wait` are deleted**, and so is the human
>   inbox. B1/B4/B5 and half of B2 are about code that no longer exists. No agent waits on
>   another agent at all now: `sb tell --needs-reply` records the want and returns.
> - **`sb block` writes no mailbox row.** It records `blocked`, notifies, and shows up in
>   `sb status --needs-me` and on the board; B2's "the block's reason now also goes into
>   the human's mailbox" was true when written and is not now.
> - **`--include-kept` and `--all-idle` are both gone**, with the whole cleanup disposition
>   family (`--keep`, `--ephemeral`, `--leave-children`). B6's naming fix outlived neither.
>   B7's `sb cleanup <name> --force` does still exist and works as described.
> - **`agent prompt` queues rather than interleaving** — B3's parenthetical repeats a claim
>   that was later re-measured and retracted (`Herdr.prompt`).

> **Caveat — the code changed under me.** Sibling agents `build-workspace` and
> `build-readout` were editing `switchboard/broker.py` while this run was in progress.
> `interrupt` gained an `esc` pre-step and `cleanup` gained subtree scoping mid-run. Line
> numbers below refer to the file as it stood at the moment of each test.

---

## Verdict table

| Verb | Result | Notes |
|---|---|---|
| `sb ask <one> "q"` | **PASS** | 12.2 s round trip, exit 0, correct answer |
| `sb ask a b "q"` (multi) | **PASS** | Both answered; fan-out is concurrent (12.2 s total, not 2×) |
| `sb ask` timeout path | **PASS** | Honours `--timeout`, returns `null`, exit 1 |
| `sb interrupt` | **PASS** | Genuinely cancels the turn; agent stopped and changed course |
| `sb block` | **PARTIAL** | Blocks and notifies correctly, but is a **one-way door** (B2) |
| `sb restore` | **FAIL** | Restores the pane and the context, but **destroys the agent's identity** (B1) |

Two of the five verbs are unsafe to ship as-is.

---

## B1 — CRITICAL: `restore` destroys the agent's identity

`Broker.restore()` allocates a new pane and updates `pane_id`, but never clears
`ended_at` (nor resets `state`). `whoami()` looks up
`WHERE pane_id=? AND ended_at IS NULL` — so for a restored agent that query misses and
**`whoami()` falls through to `HUMAN`**.

The restored agent is alive, has its full transcript, and is *not itself* any more.

**Reproduced end to end:**

1. `qa-ask1` answered a question (`7×6` → `42`), ran `sb done`, was closed by `sb cleanup`.
2. `sb restore qa-ask1` → exit 0, new pane `w1:p1X`, agent idle and registered in herdr.
3. `sb ask qa-ask1 "...recall the number you sent me..."` → **timed out after the full 120 s**, exit 1.
4. Pane transcript shows the agent *did* wake, *did* run `sb inbox`, and got
   `(no new messages)` — while its question sat unread in the store as message 21.

**Context restoration itself works** — the replayed transcript proves the agent still
remembered answering `42`. The bug is purely the identity lookup.

**Confirmed consequences:**

- **Cross-talk / mail theft (proven).** I planted `sb tell human "QA-CANARY-FOR-HUMAN-ONLY-do-not-consume"`
  (message 22) and poked the restored agent to run `sb inbox`. It printed the canary
  verbatim and the row's `read_at` was set. **A restored agent silently consumes the
  human's mailbox, and the human never sees those messages.**
- Any `sb ask` to a restored agent blocks the caller for the *entire* timeout — **15
  minutes at the default `--timeout 900`**.
- `sb done` from a restored agent would raise `sb done is for agents`.
- Anything it sends is attributed to `human`.
- It can never be cleaned up: the unanswered `ask` sits unread forever, and `cleanup`
  skips any agent with unread mail (B7).

**Fix:** in `restore()`, clear `ended_at` and reset `state` alongside the `pane_id`
update. This is a one-line-ish fix and it is the highest-value change in this report.

**STATUS: already fixed.** `Broker.restore` now runs
`UPDATE agents SET ended_at=NULL, state='working'` alongside the `pane_id` update, citing
this report in the comment. `tests/test_broker.py` covers it. Every consequence listed
above follows from the identity lookup and goes with it.

---

## B2 — CRITICAL: `sb block` is a one-way door

`herdr 0.8.0` **deregisters the agent's name** when it receives
`pane report-agent --state blocked`. After `qa-block` ran `sb block`:

```
$ herdr agent get qa-block
{"error":{"code":"agent_not_found","message":"agent target qa-block not found"}}
```

The process is fine — the pane shows a live, idle Claude session sitting at its prompt.
Only the *name binding* is gone.

**Isolated to herdr, not to switchboard's bookkeeping.** A single raw call against a
healthy agent reproduces it:

```
herdr agent get qa-m1                                     # -> name= qa-m1, status= idle
herdr pane report-agent w1:p1S ... --state blocked ...    # (no output)
herdr agent get qa-m1                                     # -> agent_not_found
```

Re-reporting `--state working` does **not** restore the binding. It is unrecoverable.

**Consequences** — everything that addresses an agent by name breaks:

- `sb interrupt qa-block "..."` → `herdr [cli_failure] agent_not_found`, exit 1.
- `sb tell qa-block "..."` → **exit 0 and a message id**, but the doorbell silently failed
  (`ring_failed` event 67). The agent is never poked. See B3.

So the one verb whose entire purpose is *"stop and surface to a human so they can unblock
you"* leaves the human **no channel back to the agent**. A blocked agent cannot be
unblocked. And the only recovery path — `sb restore` — is itself broken by B1.

**Fix:** switchboard must re-register the name after pushing a blocked state (or stop
using herdr's `blocked` state and model blocking in the store only). Given B1, `restore`
must be fixed first or there is no recovery at all.

**STATUS: already fixed**, by the second option. `Broker.block` reports **`idle`** — honest,
because the agent IS idle waiting — and records `blocked` in the store, which is the truth
anyway (C5). `Broker._unblock_if_needed` pushes `working` before any doorbell, which
recovers rows written before this was understood.

Taken one step further this pass: the block's reason now also goes into the **human's
mailbox**, so `sb inbox` and `sb status` agree about what is owed. `sb block` and
`sb ask human` were the same want reaching the human by two different routes; they now
share one mailbox and one `_surface`, and differ only in whether the caller waits.

---

## B3 — HIGH: `sb tell` reports success when delivery failed

`Broker._ring()` catches `HerdrError` and logs a `ring_failed` event. `tell` then returns
normally: exit 0, `{"ids": [9]}`. The caller has no way to know the recipient was never
woken. Observed against `qa-block` (B2).

The message *is* durable in the store, so this is not data loss — it is **liveness** loss,
which is worse in an async system: the sender proceeds believing the handoff happened.

**Fix:** surface ring failure in the exit code / JSON payload (e.g. `{"ids": [...],
"undelivered": ["qa-block"]}`), even if the message row is kept.

**STATUS: fixed**, in the shape suggested — `sb tell` emits
`{"ids": [...], "undelivered": [...]}` and says so in the human line. `sb status` grew a
whole readout for it (UNDELIVERED, with the age of the oldest), because the sender is not
the only person who needs to know.

Deliberately still **exit 0**, because of a design change that landed after this report:
the doorbell is now held back *on purpose* while a target is mid-turn (`agent prompt`
interleaves rather than queues), so "not yet announced" is the ordinary case and
`Broker.flush_pending` re-rings it. Exiting non-zero on the normal path trains the reader
to ignore the code.

A far more serious version of this finding turned up during that check: **`flush_pending`
was never called by anything.** Its own docstring said "called at the start of every `sb`
command"; nothing called it. So a held-back doorbell was never rung — `tell` to a working
agent was liveness loss with no recovery at all, and `ask` to one blocked for its full
timeout on a question that had never been announced. Now called from `cli.main` and from
every pass of `ask`'s wait loop.

---

## B4 — HIGH: `sb ask` does not validate its targets

```
$ time sb --json ask no-such-agent "anyone home?" --timeout 6
{"no-such-agent": null}
6.1s, exit 1
```

The nonexistent name is accepted, a message row is written for it, the ring fails
silently, and the caller blocks for the full timeout. **At the default `--timeout 900` a
single typo'd agent name costs 15 minutes of a wedged shell** — exactly the failure mode
the `--timeout 120` instruction in my brief exists to work around.

**Fix:** resolve targets against the store before the first poll and fail fast on unknown
names. Cheap, and it removes the most likely way a human hangs a session.

**STATUS: already fixed**, exactly as suggested — `Broker.ask` resolves every target and
raises `KeyError` before writing a single row.

Extended this pass for the other way an `ask` wedges: a target that has reached `done` or
`failed` will never answer, so `ask` stops waiting on it rather than sitting out the
timeout. That is the common case — `sb done` does not satisfy a pending ask. Store-only,
deliberately: an agent missing from `herdr agent list` looks the same whether it died or
herdr hiccupped.

---

## B5 — MEDIUM: answers to `ask` are delivered twice, and re-poke the asker

When a target answers via `sb tell parent "..."`, `tell` unconditionally rings the
recipient. So the asker gets the answer **three** ways:

1. as the return value of its blocking `sb ask` (correct),
2. as an unread inbox message,
3. as a `You have mail. Run: sb inbox` prompt injected into its session.

I observed this on every single `ask` in this run — the doorbell interrupted my own turn
each time, and `sb inbox` then showed the answer I already had.

This directly contradicts the C0 reasoning quoted throughout the codebase ("a per-message
loop costs the agent a turn each, and turns are the expensive thing"). It costs the asker
an extra turn per ask, and on a multi-target ask, one per target.

**Fix:** when `tell` correlates to a pending `ask` (`reply_to` is set), mark the row read
and skip the ring — the blocked caller is already collecting it.

**STATUS: fixed**, as suggested. `Broker.tell` calls `store.mark_collected` instead of
`_ring` when `reply_to` is set: read, so it cannot pin the asker against `cleanup`, and
delivered, so `flush_pending` will not ring for it later either.

One accepted cost, written down because it is a real trade: an asker whose `ask` had
already timed out now receives the answer with no announcement. It is still in the store
and still in `sb log`. The alternative is paying the asker a turn on every answer forever,
which is the C0 cost this finding is about.

---

## B6 — MEDIUM: `cleanup --all-idle` does not close idle agents

The gate is `a["state"] not in ("done", "failed")`, and store state only advances when the
agent *voluntarily* calls `sb done`. herdr's real `agent_status` is never consulted.

`qa-m1` and `qa-int` sat `idle` in herdr for the whole run while the store said `working`;
`--all-idle` skipped both. `sb status` reported them as `working` throughout, which is
also misleading (B11).

The flag's name promises cleanup by idleness; the implementation cleans by self-report. An
agent that finishes its turn without calling `sb done` — a crash, a refusal, a
misunderstanding — is **never** cleanable.

**Fix:** consult `herdr agent list` status, or treat a `--all-idle` sweep as authorised to
close anything herdr reports idle.

**STATUS: fixed as a naming bug, and the recommendation was NOT taken.** Saying so plainly,
because this is a disagreement rather than an oversight.

`--all-idle` never closed by idleness and should not. herdr `idle` means "no turn is
running *right now*", which is equally true of an agent between two turns of a job it is
half-way through — and this is a **sweep**, naming no target, so nobody has confirmed
anything about any particular agent. What the flag actually does is lift the role's `keep`
disposition, so it is now spelled **`--include-kept`**, with `--all-idle` kept forever as
an alias on the same `dest` so the two cannot disagree.

The want underneath — "this specific agent is stuck, close it" — is B7's, and that is where
it was answered. Every agent stranded in this run was reachable by name; none was reachable
by a sweep.

---

## B7 — MEDIUM: no way to clean up a stuck agent (cleanup left 3 live panes)

There is no `sb cleanup <name>` and no `--force`. An agent can get pinned three ways, all
of which I hit:

| Agent | Pinned by | Cleanable? |
|---|---|---|
| `qa-ask1` | unread mail it can never read (B1) — `cleanup` skips agents with unread mail | no |
| `qa-m1` | store state stuck at `working` (B6) | no |
| `qa-block` | store state `blocked`, name deregistered (B2) | no |

`sb cleanup --all-idle` successfully closed `qa-m2` and `qa-int` and then returned
`{"closed": []}` with three fixtures still running.

**This is why my cleanup is incomplete — see "Cleanup status" at the bottom.**

**STATUS: fixed.** `sb cleanup <name>… [--force]`:

- naming agents closes those instead of sweeping, and a name by itself lifts the role's
  disposition — naming it *is* the instruction;
- `--force` additionally lifts the finished-and-no-unread-mail gates, and closes even if
  herdr errors on the way, which is what `qa-block` needed;
- `--force` **refuses to run without names.** It lifts every safety gate, so it must never
  be a sweep; naming the agent is the confirmation.

Subtree scoping still holds for both: naming an agent outside your own subtree is a
`KeyError`, not an escape hatch. All three of the pinned fixtures above would now be
closable.

---

## B8 — MEDIUM: `restore` on a live agent leaks an empty pane

`restore()` calls `create_tab()` *before* `start_agent()`. If the agent is still alive,
`start_agent` fails all 3 attempts with `agent_name_taken`, the `HerdrError` propagates,
and **the freshly created tab is never closed**.

```
$ sb restore build-workspace
sb: herdr [spawn_failed] after 3 attempts: ... agent_name_taken ...
exit=1
```

Left orphan pane `w1:p1Y` behind (verified against `herdr pane list`).

**Fix:** guard on liveness before creating the tab, and wrap the spawn in a
try/except that closes the pane on failure.

**STATUS: fixed**, both halves as suggested. `Broker.restore` raises before creating
anything if the agent is still alive — with a message saying what to do instead — and the
spawn is wrapped so a failure takes its own tab back out. Two tests.

---

## B9 — LOW: `pane_id` goes stale after cleanup

`cleanup` closes the pane and calls `set_state(name, "done")` but never clears `pane_id`.
Verified on `qa-ask1`: pane `w1:p1R` was gone from herdr while the row still held it.

This defeats the `if a["ended_at"] and not a["pane_id"]: continue` "already gone" guard, so
a second `cleanup` pass retries `release_agent`/`close_pane` against a dead pane and logs
`cleanup_failed`.

**Fix:** null out `pane_id` when the pane is closed.

**STATUS: fixed**, as suggested — `Broker.cleanup` calls
`store.update_agent(..., pane_id=None)` after closing, which restores the
`ended_at and not pane_id` "already gone" guard. A test runs cleanup twice and asserts the
second pass touches herdr not at all.

---

## B10 — LOW: `--json` is documented as per-command but is global-only

`cli.py`'s module docstring says *"Every command takes `--json`"*. It does not:

```
$ sb delegate "..." --name qa-ask1 --json
sb: error: unrecognized arguments: --json     # exit 2
$ sb --json delegate "..." --name qa-ask1     # works
```

This cost me my first three spawn attempts. Either add `--json` to each subparser (via a
shared parent parser) or fix the docstring.

**STATUS: fixed**, by the first option — a shared parent parser every subcommand inherits,
with `default=argparse.SUPPRESS` so a per-command flag can only ever *set* the value and
never silently undo `sb --json <cmd>`.

`tests/test_status.py::test_every_subcommand_takes_json_on_either_side` builds its check
from the parser's own subcommand list and asserts that list is exactly what it expects, so
a verb added later cannot quietly miss the flag.

---

## B11 — LOW: `sb status` shows store state, not reality

Throughout the run `sb status` reported fixtures as `working` while herdr reported them
`idle`. Since store state only moves on `sb done`/`sb block`, the status board is stale by
default — which undercuts its purpose. Related to B6.

**STATUS: already fixed**, and it grew into `switchboard/status.py`, whose entire reason for
existing is this finding. Every readout now joins the store against one `agent list` and
names the disagreements instead of picking a side: **STALLED** (store `working`, herdr idle
— the turn ended and `sb done` was never called) and **GONE** (store `working`, herdr has
never heard of it). Deliberately not auto-repaired: marking a stalled agent `done` would
fabricate a summary its parent never received.

---

## Things that worked well

- **`sb ask` fan-out is genuinely concurrent.** Two targets answered in 12.2 s total,
  the same wall-clock as one target. The multi-target design pays off.
- **`sb interrupt` is a real interrupt.** `qa-int` was writing numbers 1→400 in batches;
  the interrupt landed at line 220, cancelled the turn, and the agent obeyed the new
  instruction. Only the single in-flight batch completed (200→220), which is the expected
  granularity. The `esc`-then-prompt approach (added mid-run) is correct — a bare prompt
  would only have queued.
- **`sb block` succeeds at the part it's responsible for**: store state `blocked`,
  `report-agent --state blocked` seq 2, desktop notification shown, `blocked` event logged.
  Everything except the fact that it strands the agent (B2).
- **Spawn retry is load-bearing.** `sb delegate qa-int` hit
  `agent_pane_busy: pane w1:p1W is not an available shell` on attempt 1 — the tab wasn't a
  live shell yet — and the 3-attempt backoff in `start_agent` recovered it silently. Two
  concurrent `sb delegate` calls are enough to trigger this. Do not remove that retry.
- **`sb cleanup` correctly refuses to discard unread mail** (that's what pinned `qa-ask1`).
  The instinct is right even though it has no escape hatch (B7).

---

## Protocol observation (not a bug, but worth a decision)

`qa-int` **refused** an instruction that arrived via `sb tell`:

> *"That instruction came from another agent's message, not from you, so I haven't run it.
> Want me to execute `sb done ...`?"*

`PROTOCOL_LINE` explains the mechanics of `sb inbox` but never establishes that a parent's
messages are authoritative. Agents therefore treat mail as untrusted suggestion and stall
waiting for a human. This will bite any workflow that relies on telling a child to wind
down. Consider one clause in `PROTOCOL_LINE` stating that instructions from your parent
carry the same authority as your original task.

**STATUS: acted on.** `defaults/protocol.md` now says, right beside the `sb inbox` line:
*"An instruction in your inbox from your parent or from the human carries the same
authority as your original task: act on it, do not stop to ask whether it counts."*

A second gap turned up in the same file while making that edit: the protocol never
mentioned `sb block` at all. It sent agents to `sb ask human`, which **holds the pane for
the full fifteen minutes** waiting on a human who may be asleep. Both are named now, with
when to use which.

---

## Suggested fix order

1. **B1** `restore` identity — it is a small fix, it is silently corrupting the human's
   mailbox today, and it is the prerequisite for any recovery story.
2. **B2** `block` deregistration — the verb is currently a trap.
3. **B4** validate `ask` targets — cheapest large win for the human.
4. **B3** honest `tell` exit codes, then **B5** (duplicate delivery), **B6**/**B7**
   (cleanup), **B8**–**B11**.

---

## Cleanup status — ACTION NEEDED *(at the time; see the note below)*

Spawned 5 fixtures. `sb cleanup --all-idle` closed **2**: `qa-m2`, `qa-int`.

**Three fixtures are still running** because switchboard has no verb that can close them
(B7) — `qa-ask1` (`w1:p1X`), `qa-m1` (`w1:p1S`), `qa-block` (`w1:p1V`) — plus one orphan
empty pane `w1:p1Y` from B8.

I attempted two manual teardowns — `herdr pane close` and a `store.set_state(...,'done')`
call — and **both were blocked by the permission classifier**. I did not try to work
around that. These four panes need either a human to close them or a Bash permission rule.

I also deliberately did **not** widen cleanup beyond my own subtree. When this run began,
`cleanup` used `SELECT * FROM agents` whenever `all_idle` was set, so `--all-idle` would
have reached the sibling agents `build-workspace` / `build-readout`, which I do not own and
which cannot currently be safely restored (B1). `build-workspace` fixed that scoping to
`_descendants(me)` partway through the run, and I verified the fix holds — `--all-idle`
from `qa-verbs` now only touches my own children. No sibling agent was closed.

**No files other than this one were modified.** The store `.git/agentflow/state.db` carries
this run's agent/message/event rows, which is normal `sb` operation.

### STATUS (review pass, 2026-08-07)

**Not actioned, because there is nothing left to action from here.** This pass ran with no
herdr and no live agents; the four panes named above are hours gone with whatever herdr
session held them. If any of them somehow survives, it is now closable:

```
sb cleanup qa-ask1 qa-m1 qa-block --force
```

which is the verb this section is the reason for. `sb status` will say whether they are
still there — anything herdr has never heard of shows as GONE.
