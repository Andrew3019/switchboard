# Phase 1 acceptance test — live, adversarial, against the plan's own "done when"

Run 2026-08-09 by agent `accept-phase1` (role qa). Nothing was fixed, installed, pushed
or merged; `main` untouched.

**Verdict: 2 of 4 criteria pass, 1 passes, 1 fails.**

| criterion | verdict |
|---|---|
| a fan-out of six agents starts six agents | **PASS** |
| every `done` wakes its parent without a heartbeat | **FAIL** — the timer half is not running and cannot run |
| `cleanup` always explains itself | **PASS** |
| a blocked agent stays blocked until Andrew answers | **HALF** — it stays blocked against the phase-1 build, but any old-build `sb` in the fleet cancels it, and Andrew's answer cannot be delivered anyway |

The biggest thing found is not on that list: **none of phase 1 is in force for agents,
because agents run `sb` from PATH and PATH `sb` is the `main` build.** It is not a
theoretical staleness — it cancelled three real blocks during this test. See §5.

---

## 0. Which binary produced which result

Two builds are live on this machine at once and they behave differently, so every result
below names its binary.

- **phase-1 build** = `/Users/andrew/.herdr/worktrees/switchboard/integrate-phase1/bin/sb`,
  worktree on branch `phase-1` at `ec2abf9`. Written below as `$SB`.
- **PATH build** = `sb` → `/Users/andrew/.local/bin/sb` → symlink to
  `/Users/andrew/Code/switchboard/bin/sb`, the main checkout, on `main` at `f6bcd58`.
  This is the `sb` every agent in the fleet runs, because the protocol tells them to type
  `sb`.

Both resolve to the same store (`git rev-parse --git-common-dir` → the shared `.git`), so
they write to one database: `/Users/andrew/Code/switchboard/.git/agentflow/state.db`.

Where a result had to be read without side effects, it was read from that database
**read-only** (`sqlite3 … ?mode=ro`) rather than through `sb`, because every `sb`
invocation runs `flush_pending` and would have been the very doorbell under test.

I could not fast-forward this worktree onto `phase-1` — `git merge --ff-only phase-1` was
refused by the harness's permission classifier — so this report is committed on
`accept-phase1`, which is branched from `main`. The report is about `phase-1`; only the
file's branch is different.

**Suite:** `pytest -q` on the `phase-1` worktree with
`/Users/andrew/anaconda3/bin/pytest` (python 3.11.5 — the only interpreter here that has
both pytest and `tomllib`): **1731 passed in 105s**. Matches the integration report.

---

## 1. Six for six — PASS

Six agents delegated back to back with the phase-1 build, trivial throwaway task, each
told to report with the phase-1 binary:

```
$SB delegate '<trivial task>' --name probe1..probe6 --role worker --model cheap
```

| agent | spawn call | outcome |
|---|---|---|
| probe1 | 6.7 s | done, `$0.17` |
| probe2 | 6.2 s | done, `$0.17` |
| probe3 | 6.7 s | done, `$0.20` |
| probe4 | 7.3 s | done, `$0.17` |
| probe5 | 6.7 s | done, `$0.17` |
| probe6 | 7.3 s | done, `$0.17` |

All six really ran: `$SB inspect <name> -n 6` shows non-zero spend on every one (the
`0% 1M │ $0.00` signature of a never-started agent appears nowhere), all six wrote a
`done` event and a `[done] probe ok` message, and all six have their own `session_id`
recorded — which only gets written when the agent itself runs `sb`. Total wall clock for
the fan-out, 41 s. Nothing came near the ~3-minute retry ceiling; no retry was needed at
all, so the retry path itself is **untested live** here.

Failure loudness, both cases I could reach:

- Duplicate name: `$SB delegate … --name probe1` → `sb: the agent name 'probe1' is
  already taken`, no name returned.
- `$SB start "trivial"` inside a worktree → refused with the main checkout named, exit
  code 1. (Item 1.7's second half.)

**Not tested:** `ForkFailed` and `TaskUndelivered`. Neither is reachable from an agent
that already has a worktree — children inherit the caller's space and never fork — and I
was not going to break herdr to induce them. They are covered by unit tests and by
reading `_fork_for` / `_spawn`; I did not see them fire.

**Incidental, and it refutes item 1.2 again:** the `agent start` argv logged for probe6
contains exactly **one** `--append-system-prompt`, 5082 characters long, holding protocol
+ role concatenated — and it is the *new* protocol text ("no agent reads it, and a human
reads it only when you block"). Nothing is dropped, and the phase-1 prompts are what the
probes ran on.

---

## 2. Every `done` wakes its parent, with no heartbeat — FAIL

This is the one the brief expected to be half-true, and it is worse than half.

### 2.1 What actually happened

All six probes reported `done` between 23:08:32 and 23:09:06. I was mid-turn throughout,
so each `done` logged `ring_deferred accept-phase1` and the message stayed
`delivered_at = NULL`. I then ran **no `sb` command for 150 seconds** and re-read the
store directly: still six messages, all `delivered_at = NULL`. They stayed undelivered for
over fifteen minutes. Nothing woke me. I eventually read them myself with `sb inbox`.

### 2.2 Why — two independent reasons, both needing an install

1. **The running collector predates the fix.** There is exactly one collector alive
   (`pid 41808`, `python -m switchboard.collector`), started **2026-08-08 14:41:30** —
   before this code existed. Its published state block in
   `.git/agentflow/panel/snapshot.json` is
   `{pid, started_at, polls, errors, collected_at, wrote_at, tick_ms, last_error,
   last_error_at}` — it has none of `doorbells`, `last_doorbell`, `doorbell_error`, the
   three fields `collector.State` gains on `phase-1`. It is polling happily (54k polls,
   0 errors) and will never ring anything. It only retires when the last board closes.

2. **Even a current collector would fail every tick.** `collector.ring_doorbell` runs
   `shutil.which("sb")` and then `[sb, "flush"]`. `which("sb")` is the PATH build, and
   the PATH build has no `flush` verb:

   ```
   $ sb flush
   usage: sb [-h] [--json] {start,delegate,ask,tell,…,inspect,wait,log} ...
   ```

   (`$SB flush` on the phase-1 build works: it printed `rang nobody`.) So on today's
   machine the doorbell would land in `state.doorbell_error` on every tick and ring
   nobody. That is the caveat the integration report flagged, confirmed live.

### 2.3 What the fix does and does not cover, even once installed

`sb flush` is a real, working verb and `flush_pending` is genuinely better (it now holds
mail for blocked agents rather than cancelling their block). But the trigger is only ever
the collector, and **the collector only exists while a board is open**. With no board
open there is still nothing on a timer, so a fan-out watched from a plain terminal is
exactly as silent as before. The plan's phrasing — "every `done` wakes its parent without
a heartbeat" — is not met by "…provided a board is open, and provided PATH `sb` is
current".

### 2.4 What was still doing the waking

Not a timer: other people's commands. The one delivery I observed in a quiet window
(mail to `probe-busy`, queued 23:19:03, delivered 23:19:45) was rung by a `flush_pending`
belonging to somebody else's `sb inspect accept-phase1` — the same event batch contains
`pane read w21:p1` and a `read_output` row for me. That is my parent polling me every few
minutes, i.e. a heartbeat, which is what this criterion exists to remove.

**Contamination note.** Partway through, `main-5` warned me it was about to flush the
whole fleet on Andrew's instruction. Every result in this section is from *before* that
flush, and none of it rests on a delivery — it rests on fifteen minutes of
non-delivery, on the collector's own published state, and on `sb flush` not existing on
PATH. So the warning does not touch the conclusion.

---

## 3. Cleanup always explains itself — PASS

All with the phase-1 build.

Named agent that is refused (used to be a bare `closed: (nothing)`):

```
$ $SB cleanup probe-block
closed: (nothing)
  refused probe-block: working, not finished — it has not reported an end
```

Mixed named set — the closed one and the reason for the other:

```
$ $SB cleanup probe-busy probe-sib
closed: probe-busy
  refused probe-sib: working, not finished — it has not reported an end
```

Sweep that closes nothing — the case the plan calls out:

```
$ $SB cleanup
closed: (nothing)
  refused probe1: already closed
  … (probe2–probe6, probe-busy)
  refused probe-block: working, not finished — it has not reported an end
  refused probe-sib: working, not finished — it has not reported an end
```

`--json` carries the same thing as `{"closed": [...], "refused": [{"name","reason"}]}`.
`--dry-run` still prints `would close: …`. Every gate I could reach names itself.

**One thing worth knowing before this ships.** A sweep that closes nothing prints a
refusal line for **every already-closed agent in the caller's subtree**, not just the
live ones. Mine had seven children and printed seven lines. `main-5` has 17 archived
children; the human's scope is the whole fleet, which is 190+ agents today. `sb cleanup`
run twice by Andrew would print a couple of hundred lines of "already closed" to say it
did nothing. The gate that matters would be buried by the gate that does not. Filtering
`already closed` out of the printed list (keeping it in `--json`) would cost nothing.

---

## 4. A blocked agent stays blocked until Andrew answers — HALF

### 4.1 Sibling mail does not cancel a block — PASS, against the phase-1 build

`probe-block` blocked at 23:16:07. `probe-sib` sent it ordinary mail at 23:17:24, using
the phase-1 binary. Result, read straight from the store: `probe-block` still `blocked`,
message `delivered_at = NULL`, and an event `ring_held {"reason": "blocked"}`. It stayed
on `sb status --needs-me` as `blocked: acceptance test hold`. Reproduced later with
`probe-ab` (`ring_held` at 23:31:31, still blocked). This is exactly item 1.9's fix and
it works.

### 4.2 …but any old-build `sb` in the fleet cancels it anyway

`probe-block` was unblocked at **23:18:57** by nobody's intent. The store records
`unblocked probe-block`, immediately followed by
`ring_failed {"error": "[agent_not_found] …"}` with **no `reason` key** — and the `reason`
key is only ever written by `phase-1` code. So the ring came from the **PATH (main)**
build, whose `_ring` still calls `_unblock_if_needed` before every delivery.

Who ran it: `probe-busy`, one of my own throwaway workers. It had been rung with the
standard doorbell text *"You have mail. Run: sb inbox"*, and `sb` there is the PATH build.
Its `flush_pending` then rang every agent with pending mail — including the blocked one —
and cancelled the block.

This happened **three times in one hour** to three different agents (`main-6` 23:17:17,
`probe-block` 23:18:57, `probe-sib` 23:29:46), each time attributable to an old-build
flush by the same signature.

The general statement, which is the headline of this report: **every agent runs `sb` from
PATH, PATH is the `main` build, so until the main checkout is rebuilt none of phase 1's
behaviour is in force for agents — only for whoever types the phase-1 path by hand.** The
block fix is the case where that is actively destructive rather than merely absent.

### 4.3 And the way out of a block does not work at all — new, not counted anywhere

`sb block` costs the agent its herdr **name binding**, so nothing can prompt it by name
again — including Andrew's answer.

Controlled A/B on a fresh agent, straight against herdr, no switchboard in the way:

```
# probe-ab spawned, idle, never blocked
$ herdr agent get probe-ab
{"id":"cli:agent:get","result":{"agent":{ … "agent_status":"done" … }}}

# probe-ab told to run `sb block "ab test hold"`; store now says blocked
$ herdr agent get probe-ab
{"error":{"code":"agent_not_found","message":"agent target probe-ab not found"}}
```

Same before/after on `probe-sib`: `agent prompt probe-sib` succeeded while it was idle
(23:28 tell landed), then failed `agent_not_found` at 23:28:48 once it had blocked. And
`herdr agent list` **still lists both agents**, `interactive_ready: true` — list and get
disagree, which is precisely the `name_binding_lost` signature `_binding_lost` was written
to name. It named it correctly (event 19424 carries
`"reason": "name_binding_lost"`), so that half of item 1.6 works.

The consequence is the part that matters. The human's answer path is
`_ring(answer=True)` → `_unblock_if_needed(who)` → `self.h.prompt(who, text)`. The store's
block clears on the first call and the prompt fails on the second. That exact pair is in
the log for `probe-block`: `unblocked` at 23:18:57, then `ring_failed agent_not_found` in
the same second. So when Andrew answers a blocked agent, the most likely outcome is: the
row stops saying `blocked` and drops off `--needs-me`, and the agent never hears the
answer — it sits idle with the reply unread in its inbox.

`broker.block`'s docstring says it pushes herdr `idle` rather than `blocked` *specifically
to keep the binding*. Live, the binding goes anyway. Phase 1 did not address this and
item 1.6 is only half closed: the failure is now *named*, but it still happens, and it
happens on the one path the human uses.

### 4.4 What I could not test

**Whether Andrew's own `sb tell` clears the block.** To be `HUMAN` in switchboard's eyes
a process must have no agent row for its session, which from inside an agent means
unsetting `CLAUDE_CODE_SESSION_ID` / `HERDR_PANE_ID`. Both spellings of that
(`env -u …`, `VAR= …`) were refused by the harness's permission classifier, twice, so I
did not force it. Installing proves nothing here — what this needs is either one command
typed in Andrew's own terminal, or permission to run `sb` with those two variables
cleared.

What can be said without it: the unit tests cover it directly
(`test_answering_a_block_unblocks_it_and_does_ring`,
`test_messaging_a_blocked_agent_unblocks_it_first`,
`test_held_mail_is_rung_once_the_human_answers_the_block`, all passing), and §4.3 is
strong evidence that the store transition will happen and the delivery will not.

---

## 5. Also found, nobody has counted these

1. **`sb tell` promises delivery it cannot make, to a blocked target.** The note reads
   `(<name> mid-turn or blocked — will be rung when free)`. For a blocked agent "when
   free" never comes: nothing but the human's own answer will ever ring it. Observed on
   `probe-ab` and on `main-6`. The `unreachable` note added in phase 1 does not cover this
   — it only fires on a recorded `name_binding_lost`, which a held ring never produces.

2. **The UNDELIVERED blurb in `sb status` was not updated with the block fix.** It still
   says *"The doorbell is held back while an agent is mid-turn … and released when it goes
   idle"*, which is now false for blocked agents — the per-agent column beside it correctly
   prints `blocked`, so the two disagree on the same screen.

3. **`sb interrupt` on a blocked agent would leave the row blocked forever.** `interrupt`
   rings with `force=True`; `_ring` skips the blocked gate under force but only calls
   `_unblock_if_needed` when `answer=True`, and interrupt never sets it. So a successful
   interrupt would resume the agent while the store still calls it `blocked` — it would sit
   on `--needs-me` with a stale reason and every later doorbell would be `ring_held`. I
   could not complete this one live because the interrupt failed earlier, on the lost name
   binding of §4.3 — so it is read from the code, not observed.

4. **`sb start` has no protection outside the phase-1 build.** `$SB start` refuses inside a
   worktree; the PATH build does not. I proved this the expensive way: my contrast command
   created a live top-level orchestrator `main-6` in a worktree. It is outside my scope to
   close (`sb: not yours to clean up`) and I have asked `main-5` to close it. This is the
   same "the fix is only in a binary nobody runs" problem as §4.2.

5. **`sb cleanup`'s refusal reason prints the store's state verbatim**, which is right, but
   note that during this run a blocked agent was reported as `working, not finished`
   because an old-build flush had already unblocked it. The message was accurate; the
   state under it was not. Nothing to fix in `cleanup`.

---

## 6. Throwaway agents

Created and closed: `probe1`–`probe6`, `probe-busy`, `probe-block`, `probe-sib`,
`probe-ab` — all closed with `$SB cleanup`, the last three with `--force`.
Not closed: **`main-6`**, a top-level orchestrator created by my mistake (see §5.4);
`sb cleanup main-6 --force` is refused because it is not in my subtree, and `main-5` has
been asked to close it.
