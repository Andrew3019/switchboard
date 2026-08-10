# A sweep that says what it kept, and a block that costs nothing

Two findings from acceptance run 4 (`audit/phase1-acceptance-4.md`, §5 and §4), fixed on
branch `fix-cleanup-silence` off `phase-1` (`5111d89`). Proven in two throwaway clones,
never against the live fleet.

## The instances

`git clone /Users/andrew/Code/switchboard` twice, under this session's scratchpad:

| clone | branch | why |
|---|---|---|
| `sbBefore` | `phase-1` `5111d89` | the behaviour as run 4 measured it |
| `sbAfter` | `fix-cleanup-silence` `dd08c49` | the same scenario, same shapes, fixed |

Each clone has its own `.git`, so `git rev-parse --git-common-dir` gives it its own
`state.db` (`audit/isolated-instance.md`). `./bin/sb doctor` in `sbAfter` →
`store …/sbAfter/.git/agentflow/state.db`; `./bin/sb status` → `(no agents)` on both
before anything was started. Every command below was that clone's own `./bin/sb`, run
from inside that clone. Every reading of a store was `sqlite3 'file:…?mode=ro'` except
the one insert marked as such. No `sb` of any build was run in a live checkout.

**Suite:** `/Users/andrew/anaconda3/bin/python -m pytest tests -q` — **1798 passed** in
160 s (1793 before, plus the five added here).

## The scenario, identical in both clones

One `sb start` per clone, given one line of instruction: delegate a child that reports
immediately, then block. So each clone reaches the exact state run 4 §4 measured — a
blocked lead holding one undelivered child report, a board open, a collector ticking.

```
pb-lead   orchestrator  blocked   1    << UNDELIVERED 1, 27m << BLOCKED     (sbBefore)
pa-lead   orchestrator  blocked   1    << UNDELIVERED 1, 8m  << BLOCKED     (sbAfter)
```

---

## One: a blocked agent's held mail, measured

The collector publishes `doorbells` — one per `sb flush` subprocess it spawns — in the
snapshot every tick. That counter IS the process count.

**`sbBefore`, five readings a minute apart, with `pb-lead` blocked and its mail held:**

```
13:58:42  doorbells=2      14:01:42  doorbells=20
13:59:42  doorbells=8      14:02:42  doorbells=26
14:00:42  doorbells=14
```

24 processes in four minutes — one every ten seconds, `DOORBELL_GAP` exactly, and by the
end of the run 161 of them over 27 minutes. Every one spawned `sb flush`, which found the
same held message, held it again, and exited. Nothing was delivered by any of them.

**`sbAfter`, the same five minutes, the same block, the same held report:**

```
14:05:03  after doorbells=0  polls=32    | before doorbells=40
14:06:03  after doorbells=0  polls=62    | before doorbells=46
14:07:03  after doorbells=0  polls=92    | before doorbells=52
14:08:03  after doorbells=0  polls=122   | before doorbells=58
14:09:03  after doorbells=0  polls=151   | before doorbells=64
```

**0 processes across 151 ticks**, against 6 a minute still climbing next door. The
collector itself is unaffected: `polls` keeps rising, `errors=0`, `doorbell_error=None`.

### The doorbell still rings — positive control, same collector, same run

The risk in a fix like this is that the trigger is simply dead. So, in `sbAfter`, with
`pa-lead`'s mail still sitting held: one message inserted directly into that throwaway
clone's store for `pa2`, which was **not** blocked — undelivered, unread, nothing else
different.

```
14:16:52  doorbells=1   msg id=5 delivered=1
14:17:12  doorbells=1   msg id=5 delivered=1     (and no further rings)
```

One tick later the collector had spawned exactly one `sb flush`, the message was
delivered, and the counter went quiet again — while the blocked agent's mail beside it
went on producing nothing. Silent for the mail nothing can move; one ring, immediately,
for the mail a ring moves.

### The held mail still arrives when the block is answered

`pa-lead`'s child report sat undelivered for 14 minutes, on the board the whole time as
`<< UNDELIVERED 1`.

```
14:18:03   ./bin/sb tell pa-lead "HUMAN ANSWER: …"   → sent to pa-lead
           events: unblocked pa-lead
msg 1  worker-1 → pa-lead  delivered_at=1786396683  read_at=1786396690   [done] probe child reporting in
msg 6  human    → pa-lead  delivered_at=1786396683  read_at=1786396690   HUMAN ANSWER: …
```

Both delivered on the same second the human's answer landed, both read seven seconds
later, and `pa-lead` went on to report `done`. The answer's own `sb tell` flushes in its
own process — which is why the collector never needed to look.

The store's own count of what the doorbell used to be doing agrees: `ring_held pa-lead`
appears **once** in `sbAfter` (the child's `sb done` ringing its blocked parent, which is
correct and unchanged), and never again.

### What changed, and what did not

`collector.ring_doorbell` asks `AgentStatus.ringable` instead of `a.undelivered`.
`ringable` is `undelivered` minus the one case a ring cannot move: an agent that is
blocked, unless the human's own answer is among its mail — the one ring `broker._ring`
lets through a block. The predicate lives in `status.py` beside the count it refines, so
the doorbell and `flush_pending` cannot come to disagree.

Nothing about the mail changed. It stays `delivered_at IS NULL`, stays in `undelivered`,
stays on the board, stays in `--needs-me`, and `flush_pending` still re-derives it on
every `sb` command anyone runs. What stops is the rediscovering.

---

## Two: a sweep that closes something now accounts for what it kept

Same two clones, the same fleet shape: one finished worker, one blocked lead.

**`sbBefore`** — `pb-lead` is blocked, holding 27-minute-old mail, and the sweep does not
mention it:

```
$ ./bin/sb cleanup --dry-run
would close: worker-1

$ ./bin/sb cleanup
closed: worker-1
```

**`sbAfter`**, same command:

```
$ ./bin/sb cleanup --dry-run
would close: worker-1
  refused pa-lead: role orchestrator is kept, not closed (--include-kept)
  refused pa2: blocked, not finished — it has not reported an end

$ ./bin/sb cleanup
closed: worker-1
  refused pa-lead: role orchestrator is kept, not closed (--include-kept)
  refused pa2: blocked, not finished — it has not reported an end

$ ./bin/sb cleanup                       # a second sweep, closing nothing — unchanged
closed: (nothing)
  refused pa-lead: role orchestrator is kept, not closed (--include-kept)
  refused worker-1: already closed
  refused pa2: blocked, not finished — it has not reported an end

$ ./bin/sb cleanup --json
{"closed": [], "refused": [{"name": "pa-lead", …}, {"name": "worker-1", "reason": "already closed"},
 {"name": "pa2", …}], "expected": ["worker-1"]}
```

### The judgement about noise, and where it is made

A sweep is *for* skipping most of the fleet, so listing every skip grows with the fleet
and buries the line that matters — which is why the silence existed in the first place.
Two kinds of refusal are the sweep doing its job and are left out of a sweep's readout:

- **a row already closed** — nothing was held back; it was closed before the sweep ran
- **an agent still working** — it will finish on its own and the next sweep takes it

Everything else held back a row a human might have meant, and is named with its reason:
blocked, `failed` with a pane herdr still has, unread mail it could still read, live
children underneath, a kept role. **Blocked is deliberately split out of the
not-finished gate**: it is the same code path as "working" and the opposite situation —
an agent that is stopped, waiting on a person, and the person most likely to see the line
is the one who just swept and is about to walk away believing the fleet is idle.

The cut is made in `broker.cleanup`, where the gates are (`CleanupResult.expected` /
`.notable`), not in the printer — so the decision about what counts as news lives next to
the code that knows why a row was held. `cli._sweep_refusals` only formats, and caps at
five lines with a `… and N more refused` tail, because past a handful the lines stop
being a report and start being a listing.

Named agents and a sweep that closed nothing are **unchanged** — they still print every
refusal, including the expected ones. `--json` is unchanged too: it carries every refusal
either way, and gains an `expected` list naming which of them the text readout considers
routine.

---

## Tests added

Five, all pinning the two decisions and nothing else. No new trick was taught to the fake
herdr.

- `test_a_sweep_that_closes_something_still_accounts_for_what_it_kept` — the cut itself:
  already-closed and working are `expected`, blocked is `notable`.
- `test_a_sweep_prints_the_row_it_left_behind` — that it reaches the person who typed the
  command, and that `--json` still carries everything.
- `test_a_long_sweep_of_refusals_ends_in_a_line_and_not_a_listing` — the cap.
- `test_a_blocked_agents_held_mail_does_not_cost_a_process_a_tick` — three ticks with the
  floor reset between them, so it is the predicate being tested and not `DOORBELL_GAP`.
- `test_the_humans_answer_to_a_blocked_agent_still_rings` — the one ring a block lets
  through.

## What is not proven

- **A deferred doorbell to a genuinely busy agent, live.** herdr reported no agent of
  mine as `working` at any moment I could catch, so the naturally-occurring
  undelivered-and-idle case had to be produced by inserting one row into the throwaway
  clone's store (marked above). The predicate is the same either way; only the way the
  state arose is synthetic. Acceptance run 4 §4 records the same difficulty.
- **Any agent kind but `claude`**, and **the live fleet** — nothing here touched it.
- **A sweep large enough to hit the five-line cap, live.** Unit test only.

## Teardown

Three throwaway agents (`pb-lead`, `pa-lead`, `pa2`) and their two children, in two
clones, none ever visible in the live fleet's store. All closed with `sb cleanup`; the two
blocked leads needed `--force`, by their own design. Both clones' herdr workspaces closed
with `herdr workspace close <id>`, the `~/.herdr/worktrees/sbBefore` and
`~/.herdr/worktrees/sbAfter` trees deleted, and the clones deleted. No process was killed,
by pid or otherwise, and **no `pkill` of any kind was used**. Both clones' collectors were
left to retire on their own once their boards closed.
