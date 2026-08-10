# Phase 1 acceptance, fourth run — isolated clones, branch `phase-1` at `5111d89`

Run 2026-08-10 04:50–05:25 by agent `accept-phase1-4b` (role qa). Nothing was fixed,
installed, pushed or merged; `main`, `DESIGN-TRUTH.md`, `BUILD-PLAN.md` and the installed
symlink are untouched. No test was added. Only this file was written.

**Verdict: all four criteria pass on their own wording, and phase 1 is still not
finished.** The fan-out defect that failed run 3 is gone — 54 spawns, 42 of them cold
first-fan-outs into brand-new clones, and not one agent was left holding no task while
`sb delegate` reported success. The doorbell was watched to wake a parent from a deferred
ring with nothing arranged by hand. But the spawn fix has replaced a silent loss with a
**loud lie in the opposite direction**: twice in this run `sb delegate` exited 1 saying the
agent "started but never took its task, so nothing was delegated" for an agent that had
taken the task and was doing the work — and one of those two had already reported `done`
one second before its row was overwritten to `failed`. Following the error's own printed
advice ("respawn it … then `sb cleanup <name> --force`") duplicates the work and kills a
live agent.

| criterion | verdict |
|---|---|
| a fan-out of six agents starts six agents | **PASS** — 7 cold fan-outs of six, 42/42 agents took their task and ran (§2). But 2 of those 42 were *reported* as failed spawns (§3), which is a new defect of the same family |
| every `done` wakes its parent without a heartbeat | **PASS** — watched end to end on the deferred path, no `sb` command by anyone, no human (§4) |
| `cleanup` always explains itself | **PASS when you name an agent; FAILS on a sweep** (§5). The specific `closed: (nothing)` + `--force` case from the brief is fixed for the case it was reported in, and reappears with a *false* reason as a consequence of §3 |
| a blocked agent stays blocked until Andrew answers | **PASS**, both halves, over 13 minutes and 85 doorbells (§6) |

---

## 0. The instances, and the proof the agents were on them

Twelve throwaway `git clone`s of `/Users/andrew/Code/switchboard`, each checked out at
`phase-1` (`5111d89`), under this session's scratchpad, named `sbA`…`sbL`. Every command
was the clone's own `./bin/sb`, always run from inside that clone. Written below as `$C`.

- **Own store.** `$C/bin/sb doctor` → `store <scratch>/sbA/.git/agentflow/state.db`;
  `$C/bin/sb status` → `(no agents)` on every fresh clone. No `a4*` name ever appeared in
  the live fleet's store.
- **Branch build, not the installed one.** The hidden `flush` verb: `./bin/sb flush` →
  `rang nobody`; the PATH-installed `sb flush`, run from inside the clone, →
  `usage: sb … {start,delegate,…}` (no `flush` on `main`).
- **The agents were on it too.** Every probe was told to print `command -v sb`, `sb flush`
  and `git rev-parse --short HEAD` into its own `done` summary. All 42 answered with their
  own worktree's `bin/sb`, with `flush=rang nobody` — a verb the installed build does not
  have — and with `head=5111d89`, the branch tip. e.g. `a4-w3`:
  `sbpath=/Users/andrew/.herdr/worktrees/sbA/a4-w3/bin/sb flush='rang nobody'
  head=5111d89`. Every `fork` event logged
  `{"base": "phase-1", "base_fallback": null, "inherited": true}`.

**Suite:** `/Users/andrew/anaconda3/bin/python -m pytest tests -q` in `sbA`:
**1793 passed** in 127 s. No failures, no errors.

**No side effect on the live store.** Unlike runs 3 and the doorbell-path proof, no `sb`
command of any build was run in a live checkout at any point. Every reading of any store
was `sqlite3 'file:…?mode=ro'`.

---

## 1. What was actually run

54 agents in twelve clones.

| clone | what | agents |
|---|---|---|
| `sbA` | a real lead, given a task file, delegating six workers — the criterion as written | 7 |
| `sbB` `sbC` `sbD` `sbF` `sbH` `sbI` | six `sb delegate`s each, issued by the human from the clone, into a brand-new checkout parent | 36 |
| `sbE` `sbG` `sbJ` `sbK` `sbL` | doorbell measurements: a lead plus one or two children | 11 |

Every clone was new, so every fan-out was a *cold* first fan-out into a
`~/.herdr/worktrees/<clone>` that had never existed — the condition under which the old
defect struck 9 of 10 (`audit/spawn-delivery-proof.md` §4).

---

## 2. Six for six — PASS

`sbA`, the criterion in its own shape: a lead delegating six, 04:50:51 → 04:52:42.

```
a4-w1 … a4-w6   all state=done, all reported, within 04:52:14–04:54:11
```

All six ran, all six reported their own build and the branch tip. The lead's own summary
line named six successes and there were six.

Across all twelve clones: **54 spawns, 0 silent losses.** Ground truth for each was the
agent's own Claude Code transcript (`~/.claude/projects/<slug>/…jsonl`): every one of the
54 has the task text as its first user record. There is no agent in this run that sat at
`0% 1M │ $0.00` having taken no turn — the signature run 3 §2 measured twice in ten.

The re-send path is doing the work. Delegates that confirmed on the first send returned in
6–8 s; those that needed one re-send returned in 26–33 s. Both were common in every clone,
which matches the fix author's note that the first prompt after `agent start` is lost more
often than not.

**So the failure that failed run 3 did not recur, at four times run 3's scale.**

---

## 3. The new defect: a spawn that worked, reported as a spawn that failed

In `sbF`, two of six delegates exited **1**:

```
05:01:10 END a4f4 rc=1 :: sb: herdr [task_undelivered] a4f4 started but never took its
                          task, so nothing was delegated — a4f4: the text was sent 3 times
                          and the agent never took it …
05:02:33 END a4f5 rc=1 :: … same for a4f5
```

Both statements are false. Both agents took the task and did the work:

| agent | prompts sent | its own transcript's first user record | outcome |
|---|---|---|---|
| `a4f4` | 05:00:04, 05:00:26, 05:00:49 | **05:00:51.6** — the third send | `revived` 05:01:44, then `done`, `PROBE OK … head=5111d89` |
| `a4f5` | 05:01:26, 05:01:49, 05:02:13 | **05:01:59.7** — the second send | `done` 05:02:32 with `PROBE OK …` |

`a4f5` is the sharp one. Its ordering, from the store:

```
05:02:32  done   a4f5  {"summary": "PROBE OK sbpath=… flush=rang nobody head=5111d89"}
05:02:33  task_undelivered a4f5   → row set to `failed`
```

**The agent reported a successful end, and one second later the spawn path overwrote its
row with `failed`.** `sb status` then prints the contradiction on two lines of one row:

```
a4f5   worker  failed    done  …
    ✓ PROBE OK sbpath=/Users/andrew/.herdr/worktrees/sbF/a4f5/bin/sb flush=rang nobody head=5111d89
```

### Why it happens

`Herdr._took_prompt` (`switchboard/herdr.py:592-605`): **when `proof` is supplied, the
herdr status read is never consulted at all** — it is `if proof is not None: … else: …`.
So "the transcript does not show it yet" and "the agent never got it" are the same answer,
even while herdr is plainly reporting the agent `working`.

The proof (`output.task_arrived`, `switchboard/output.py:138-182`) needs the session
`.jsonl` to *exist on disk* with an `st_mtime` at or after the send. Claude Code does not
flush that file when the text is submitted. Measured here:

- `a4f5` recorded the task internally at 05:01:59.7; the file's mtime was **05:02:34** —
  a 35-second lag, against `timeouts.deliver_ms = 20000` and `retries.deliver_attempts = 3`.

So the proof is a race against a write the agent controls, and the fleet was busy: roughly
thirty Claude Code panes were live in that window (my own doing — seven clones' worth of
probes). Both failures fall inside it; the other 42 spawns, run at lighter load, all
confirmed. **The defect is load-sensitive, and a fan-out of six is precisely the load it
is sensitive to.**

### Why it matters more than a wrong exit code

The error text tells the caller what to do next
(`switchboard/broker.py:217-219`):

```
… so nothing was delegated — … Nothing is running that work; respawn it.
The pane is still open: `sb inspect <name>`, then `sb cleanup <name> --force`
```

Both instructions are harmful in this state. Respawning duplicates an agent that is
already doing the work — in a six-way fan-out an orchestrator that trusts this starts
seven or eight. `sb cleanup --force` on a `working` agent skips every gate and closes its
pane mid-turn; the code knows this (`cleanup_forced_live`) and does it anyway, because
naming the agent is the confirmation. A lead following its own tool's advice therefore
kills a live worker and starts a second one to redo its work.

This is a **regression in kind, not in degree**: run 3's complaint was that a caller was
told six when it had five. A caller is now told four when it has six, and told to act on
it.

**The one-line shape of a fix, for whoever picks this up (I fixed nothing):** the status
read that `proof` displaced is exactly the evidence that distinguishes these two cases. An
agent that herdr reports `working` after the send has started a turn; that is not proof
the *text* arrived, but it is proof the spawn is not the dead-pane case this exception
describes, and it should not be reported as one.

---

## 4. Every `done` wakes its parent, with no heartbeat — PASS

Clone `sbL`, and this is the clean measurement runs 2 and 3 never got:

| time | what |
|---|---|
| 05:18:44 | `./bin/sb start … --name a4l-lead --no-focus`; the board it opens elects a collector (pid 6072, the clone's own) |
| 05:19:01 | the lead delegates `a4l1` (sleep 5 s, then one `sb done`, nothing else) |
| 05:19:37 | the lead delegates `a4l2` (sleep 600 s — so it will run no `sb` at all in the window) |
| 05:19:39 | `a4l1` calls `sb done`. The lead is mid-turn, so the ring is **deferred**: event `ring_deferred a4l-lead`, `delivered_at = NULL`. **This is the last `sb` command any process ran.** |
| 05:19:51 | `agent prompt a4l-lead You have mail. Run: sb inbox`, `delivered_at` set — 12 s later, by the collector's doorbell |
| 05:19:57 | `read_at` set |
| 05:20:02 | the lead ran `sb block "WOKEN by the doorbell alone"` |

The collector published `doorbells: 2, doorbell_error: None, errors: 0`. I ran nothing in
that window; `a4l2` was asleep; every reading was read-only sqlite. **A parent genuinely
woken by its child's report, with nothing arranged by hand, no heartbeat and no human.**

`doorbell_error: None` is what settles run 3 §3.2: the installed build has no `flush` verb,
so a doorbell that had shelled out to PATH could not have exited 0 once. The doorbell is
running its own checkout's `bin/sb`. Across the whole run, over 90 doorbells in `sbA` and
more elsewhere, `doorbell_error` was `None` every time I read it.

**Two things worth knowing that are not defects but are structural, and Andrew should say
out loud that he accepts them:**

1. **A board must be open.** Unchanged. `ring_doorbell` is called only from
   `collector.tick`, and only a renderer keeps a collector alive. A fan-out watched from a
   plain terminal is still silent. (Confirmed incidentally: when I closed the last board in
   each clone, that clone's collector retired by itself within a minute — no orphans.)
2. **Most of the time the doorbell is not what wakes the parent.** In `sbE`, `sbG` and
   `sbK` the child's own `sb done` rang the idle parent directly, within 1–2 seconds, and
   the collector's doorbell counter stayed at 0 or 1. Deferral only happens when herdr has
   the parent as `working`, which in practice means the parent is itself inside an `sb`
   command. That is fine — but it means the doorbell is a backstop that fires rarely, and
   a run that does not force the deferred path is not testing it. Runs 2 and 3 both failed
   to isolate it for this reason; §4 above is the forced case.

### Mail to an agent that has finished — PASS

`sbA`, `a4-w1` had reported `done` and herdr answered `agent_not_found` to its name.

```
$ ./bin/sb tell a4-w1 "are you there? (unreachable probe)"
sent to a4-w1 (a4-w1 UNREACHABLE — herdr no longer answers to its name and the doorbell
will not ring again; the message is stored and still in its inbox, but somebody has to go
to its pane)
```

Store, over the following three minutes: `ring_skipped {"reason":"finished"}` ×1,
`mail_unannounced` ×1, `delivered_at` set, `read_at` NULL, and **`ring_failed`: 0** — run 3
§6.1 measured 21 in 71 seconds and rising. `./bin/sb cleanup a4-w1` → `closed: a4-w1`, with
no `--force`. Both halves of that fix hold.

### Still unfixed: held mail keeps the doorbell spawning processes

Run 3 §6.2, unchanged and now much more visible because the doorbell actually works.
`a4-lead` sat blocked with two held messages from 04:53:36. `ring_doorbell` gates only on
"is anything undelivered", and mail held for a blocked agent is undelivered by definition:

```
04:56  doorbells 27
04:59:18 → 05:00:19   41 → 47   (one every ~10 s, DOORBELL_GAP)
05:07:08  doorbells 85
```

**85 `sb flush` subprocesses spawned to ring an agent that is blocked and must not be
rung**, for one block held 13 minutes. Cheap each, unbounded in total, and it scales with
how long a human takes to answer.

---

## 5. `cleanup` always explains itself — PASS named, FAIL on a sweep

Named agents always get a reason, and the reasons are specific:

```
sb cleanup a4-lead      → closed: (nothing)
                            refused a4-lead: blocked, not finished — it has not reported an end
sb cleanup a4-w1        → closed: a4-w1                     (finished + unreachable, no --force)
sb cleanup a4f5         → closed: (nothing)
                            refused a4f5: recorded failed, but herdr still has its pane — nobody reported this end
sb cleanup (2nd sweep)  → closed: (nothing)
                            refused a4-lead: blocked, …
                            refused a4-w1: already closed   (…and the other five)
```

`--json` carries `{"closed": […], "refused":[{"name","reason"}]}` in every case.

### The brief's specific case

`sb cleanup` on a finished agent printing `closed: (nothing)` and needing `--force`
**does not happen on this branch for the case it was reported in**: `a4-w1` had finished,
had unread mail, and had lost its name binding — the exact jam run 3 §6.1 described — and
it closed on the first try with a plain `closed: a4-w1`.

It reappears, once, and as a **consequence of §3**: `a4f5` finished and reported, §3
overwrote its row to `failed`, and `cleanup` then refuses it with
`recorded failed, but herdr still has its pane — nobody reported this end`. That sentence
is false — `a4f5` reported an end at 05:02:32 and its summary is in the same store — and
`--force` was the only way to close it. So the criterion's letter holds (it explains
itself) while the explanation is wrong, and the wrongness comes from the other fix.

### Where it is genuinely silent

`cli.py:936` — `if names.refused and (args.name or not names)`. A sweep that closes at
least one agent prints **no** refusals at all. Flagged in runs 2 and 3; confirmed again,
and this run has two cases where the silence hid the row that mattered:

```
$ ./bin/sb cleanup           # in sbF
closed: a4f1, a4f2, a4f3, a4f4, a4f6
```

— five names, silently omitting `a4f5`, the one row that was stuck and needed `--force`.
You have to notice a missing name to know anything happened.

```
$ ./bin/sb cleanup           # in sbK
closed: a4k1
```

— and `a4k-lead`, blocked and waiting on a human, is not mentioned.

`--dry-run` is silent the same way: `would close: a4-w1 … a4-w6` with no word that
`a4-lead` would be refused. The command whose entire purpose is "tell me what will happen"
does not say what will not.

On the plan's word *always*, this is a failure. On the code's own documented reading
("a sweep is expected to skip most of the fleet") it is a choice. Somebody should decide;
my own reading is that "closed: five of the six you asked about" is exactly the shape of
silence item 1.4 was written to end, and that a sweep should at minimum say
`(1 refused — sb cleanup <name> to see why)`.

---

## 6. A blocked agent stays blocked until Andrew answers — PASS

`a4-lead` blocked at 04:53:36 with `WOKEN: read 4 messages from my children`.

- **It stayed blocked for 13 min 34 s**, through **85 doorbell firings** and through two
  further children reporting `done` (`ring_held a4-lead {"reason":"blocked"}`,
  `delivered_at = NULL`). `sb status --needs-me` kept printing `<< BLOCKED` and
  `<< UNDELIVERED 2, 13m`.
- **The human's answer works, end to end.** Inside the clone my session has no agent row,
  so `sb` resolves me as `HUMAN` and this is the real answer path:

```
05:07:10  ./bin/sb tell a4-lead "HUMAN ANSWER: …"   → sent to a4-lead   (no UNREACHABLE note)
05:07:10  unblocked a4-lead
05:07:10  all three held messages delivered_at set
05:07:22  read_at set — the agent read them
```

`herdr agent get a4-lead` answered while it was blocked, i.e. `sb block` still does not
evict the name. Nothing in this run contradicts run 3 §5.

---

## 7. Where two fixes combine

Looked for specifically, as the brief asked. The spawn path now carries a build pin *and*
a transcript proof; the delivery path carries the doorbell *and* the unreachable guard.

- **Spawn proof × the row's state, and then × `cleanup` — §3 and §5.** The sharp one, and
  it is a genuine interaction and not one fix's bug: the proof writes `failed` over a row
  that `sb done` had just set, and `cleanup`'s `failed`-row gate then refuses that row with
  a reason that the store's own `done` event contradicts. Neither author could have seen it
  alone: the spawn author never had an agent report before the timeout, and the cleanup
  gate was written when `failed` really did mean "nobody reported this end".
- **Doorbell × block — §4, last part.** The doorbell working turns a held block into 85
  spawned processes. Before the doorbell fired, that gate cost nothing.
- **Doorbell × `done`'s eviction — fixed.** Run 3 §6.1's endless ring loop is gone
  (`ring_failed`: 0, and `mail_unannounced` instead), and the row it jammed now closes
  without `--force`.
- **Pin × doorbell — compounding, as intended.** The board's collector runs the clone's
  build (`doorbell_error: None` throughout), the spawned agents run their worktree's
  `bin/sb`, and the children fork from `phase-1`. All three had to be right for §4 to
  happen at all, and they were.
- **Transcript proof × a shared cwd — a hazard I did not manage to trigger.**
  `task_arrived` matches by *content*, over every `.jsonl` in the cwd's transcript
  directory. Two agents given the same task text in the same cwd — which is what
  `sb delegate --workspace <existing>` produces — could confirm each other. The
  `since - 5 s` floor makes the window small (two sequential delegates are ≥6 s apart), so
  I could not construct it, and I am reporting it as a hazard to look at rather than a
  finding.

---

## 8. Smaller things, and what I did not test

- `sb status`'s UNDELIVERED blurb still says *"the doorbell rings when the agent next goes
  idle"* for a **blocked** agent, where it will not ring until a human answers. Same family
  as run 1 §5.2 and run 3 §6.4.
- `sb start` refuses a multi-line task with a genuinely useful message
  (`herdr refuses any agent argument containing a newline … put multi-line guidance in a
  file`). Noted as working, not as a defect.
- **Not tested:** the live fleet — nothing in this run touched it, so nothing here says how
  the installed build behaves against Andrew's real store. **Not tested:** any agent kind
  but `claude`; the proof in §3 is Claude Code's transcript and another kind falls through
  to the weaker `working` fallback. **Not tested:** `sb restore` re-binding an evicted name.
  **Not tested:** `--workspace` delegation at all, so the §7 hazard is unconfirmed in both
  directions. **Not measured:** the rate of §3 as a function of load — I have 2 in 42, both
  inside one busy window, which is enough to say it happens and not enough to say how often.
- Nobody typed into my agents' panes this run — the thing runs 2, 3 and the doorbell-path
  proof each recorded. I looked and saw none.

---

## 9. Verdict

**Phase 1 is not finished, but it is closer than run 3 left it, and the two items run 3
left open are both genuinely closed.** The fan-out no longer loses agents: 54 spawns, 42 of
them cold, every one took its task. The doorbell rings with its own build and was watched
to wake a parent from a deferred ring with nothing arranged by hand. Mail to a finished
agent no longer loops or jams its row. Blocking holds against 85 doorbells and yields only
to the human.

What is left, in the order I would fix it:

1. **§3 — `sb delegate` reports a working spawn as a failed one, and tells the caller to
   respawn it and force-close it.** Two of forty-two, under exactly the load a six-way
   fan-out creates. One of those two had already reported `done` before its row was
   overwritten to `failed`. This is the same class of defect as the one phase 1 was
   supposed to end — a caller acting on a spawn report that is not true — and it is worse
   in one respect: the remedy it prints destroys a live agent.
2. **§5 — a sweep that closes anything explains nothing.** Twice this run it silently left
   behind the one row a human needed to know about.
3. **§4 — 85 spawned processes for one block held 13 minutes.** Bounded by nothing but the
   human's response time.

Then the two structural facts in §4 that are not bugs and want an explicit decision: the
wake-up only exists while a board is open, and in the common case it is `sb done`'s own
direct ring rather than the doorbell that does the waking.

---

## 10. Throwaway agents and teardown

54 agents in twelve clones (`sbA`…`sbL`), none ever visible in the live fleet's store.
All closed with `sb cleanup`; seven needed `--force` (`a4-lead`, `a4e-lead`, `a4f5`,
`a4g-lead`, `a4j-lead`, `a4k2`, `a4l2` — five blocked or mid-sleep by my own design, one
the §3 casualty, one stalled). `herdr workspace list` afterwards is the pre-run baseline
exactly: `switchboard`, `main-4`, `worker-2`, `main-5`, `accept-phase1`,
`accept-phase1-4b`; the six leftover clone-directory workspaces were closed with
`herdr workspace close <id>`.

No process was killed, by pid or otherwise, and **no `pkill` of any kind was used**. Every
collector this run started retired by itself once its boards closed; the only collector
running afterwards is the live fleet's pid 1871, which was running before this began. The
throwaway worktrees under `~/.herdr/worktrees/sb{A..L}` were deleted, and so were the
clones.
