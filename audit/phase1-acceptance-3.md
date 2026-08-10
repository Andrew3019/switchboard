# Phase 1 acceptance, third and final run — isolated clone, branch `phase-1` at `1ff9285`

Run 2026-08-10 03:03–03:30 by agent `accept-phase1-3` (role qa). Nothing was fixed,
installed, pushed or merged; `main`, `DESIGN-TRUTH.md`, `BUILD-PLAN.md` and the installed
symlink untouched. Only this file was written.

**Verdict: 3 of 4 criteria pass. The fan-out criterion fails on substance — two of ten
spawns in this run produced an agent that never received its task and never ran, while
`sb delegate` reported success. All three follow-up fixes do what their authors claim.**

| criterion | verdict |
|---|---|
| a fan-out of six agents starts six agents | **FAIL** — six panes, five agents. One got no task, silently (§2) |
| every `done` wakes its parent without a heartbeat | **PASS on the mechanism, FAIL as configured** — the doorbell works end to end, but only if the `sb` on the *installed* PATH has `flush`. Nothing pins the board's `sb` (§3) |
| `cleanup` always explains itself | **PASS**, with two documented silences (§4) |
| a blocked agent stays blocked until Andrew answers | **PASS**, both halves, including the human's own answer (§5) |

New this run, and nobody has counted them: a done agent whose name herdr has evicted
drives an **endless ring loop** — now that the doorbell actually fires, `sb flush` runs
every ten seconds forever, and the guard written to prevent exactly this never fires
(§6.1). And `cleanup` will not close that row without `--force`.

---

## 0. The instance, and the proof the agents were on it

`git clone /Users/andrew/Code/switchboard <scratch>/sb3`, `git checkout phase-1`
(`1ff9285`), driven only by the clone's own `./bin/sb`, always from inside the clone.
Written below as `$C`. A second clone `<scratch>/sbmain` on `main` (`f6bcd58`) was used
for the fork-base control in §7.

- **Own store.** `$C/bin/sb doctor` → `store <scratch>/sb3/.git/agentflow/state.db`;
  `$C/bin/sb status` → `(no agents)`. No `pa3-*` name ever appeared in the live fleet.
- **Branch build, not the installed one.** The hidden `flush` verb: `$C/bin/sb flush` →
  `rang nobody`; `sb flush` on PATH → `argparse: invalid choice: 'flush'`.
- **The agents were on it too, and this is the asymmetry the brief asked for.** Every
  worker was told to print `command -v sb` and `sb flush` and put both in its `done`
  summary. All five that ran answered with their **own worktree's** `bin/sb` and with
  `sb flush=rang nobody` — a verb the installed build does not have. e.g. `pa3-w6`:
  `HEAD=pa3-w6; log=1ff9285 …; sb path=/Users/andrew/.herdr/worktrees/sb3/pa3-w6/bin/sb;
  sb flush=rang nobody`.

**Suite:** `/Users/andrew/anaconda3/bin/python -m pytest tests -q` in the clone:
**1764 passed** (136 s). Run again inside the test by `pa3-lead` itself: **1764 passed**.

**One live-fleet side effect, disclosed.** Before starting I ran `sb status` once in
`/Users/andrew/Code/switchboard` to record a baseline. That is the installed build against
the live store and it runs `flush_pending`, so it may have delivered live mail. Nothing
else in this run touched the live store; every later reading of the clone's store was
`sqlite3 … ?mode=ro`.

---

## 1. What was actually run

`$C/bin/sb start … --name pa3-lead --no-focus`, whose task file told it to: delegate six
workers; run the test suite (a deliberately long tool call); then **stop and run nothing**;
then, when poked, read its inbox and `sb block`. The "run nothing" step is the doorbell
measurement — any `sb` command by anyone flushes the queue and destroys it.

---

## 2. Six for six — FAIL

Six forks, six pins, six `agent start`s, six boards, in 54 s (03:03:35 → 03:04:29). By
every event in the store the fan-out worked. **`pa3-w1` never ran.**

```
$ herdr pane read w20:p1 --source recent-unwrapped   # pa3-w1's pane, 12 minutes later
  … the Claude Code splash screen, empty prompt box …
  Sonnet 5 │ ░░░░░░░░░░ 0% 1M │ $0.00
```

Zero context, zero spend, no turn ever taken. herdr says `agent_status: done` (the turn
that never started has ended); switchboard's store says `working`. `sb delegate` had
returned the name to `pa3-lead`, which reported "all six delegates succeeded".

It happened again, independently, in the second clone: `pa3-mainchild`, a lone `sb
delegate`, same signature — `0% 1M │ $0.00`, one `agent prompt`, no retry. **Two of ten
spawns this run.** A control burst of three back-to-back delegates immediately afterwards
(`pa3-ra/rb/rc`) all ran and all reported, so it is intermittent, not universal.

### Why the guard did not catch it

`broker._spawn` ends with `self.h.deliver(name, task)`, whose docstring says the spawn is
not done until the task is in and that an unconfirmed prompt is re-sent. It confirms with
`Herdr._took_prompt`: snapshot `state_change_seq` before prompting, then poll until the
agent's seq moves or it enters `WORKING`.

For `pa3-mainchild` the store holds **exactly one** `agent prompt` call, rc 0, no re-send,
no `task_undelivered` event — so `_took_prompt` returned True. The seq it snapshotted at
prompt time was 2397 (`agent_status: idle`); the agent now sits at 2399, `agent_status:
done`, having never run. So the confirming state change was the agent's own status
settling after `agent start`, not it taking the prompt. That reading is an **inference**
from the two seq values; what is **measured** is that the confirmation passed, once, for a
prompt the agent demonstrably never took.

### What does surface it, and when

`sb status` shows the row as `<< STALLED` with `herdr says idle — turn ended, sb done never
called`. That is real and useful, but it arrives minutes later and only to someone reading
the tree; the parent was told "delegated" and moved on. On the plan's own wording — *a
fan-out of six agents starts six agents* — this run started five.

---

## 3. Every `done` wakes its parent, with no heartbeat

### 3.1 The mechanism now works. I watched it.

This is the first time the doorbell has been seen to ring in the real, board-driven
configuration, and it is a genuine improvement over run 2:

- The elected collector was **the branch's**. `pid 169`, cwd = the clone, and its
  published state block carried `doorbells`, `last_doorbell`, `doorbell_error` — the three
  fields only `phase-1` has. That is the fork-base fix paying off: the board a `delegate`
  opens runs the child's checkout, and the child's checkout is now on the parent's branch
  (run 2 §3.2 found an `origin/main` collector with no doorbell at all).
- `_run_doorbell`'s cwd is fixed. No `not inside a git repo` traceback appeared once.

### 3.2 …and it still rang nobody, for one remaining reason

From 03:07:47 (the lead's turn ended, herdr `idle`) to 03:13:18 — **5.5 minutes** — five
messages, four of them `done` reports, stayed `delivered_at = NULL`. No `sb` command was
run by me or by any agent in that window (I read the store read-only every 15 s). The
collector fired **55 doorbells**. Every one failed identically:

```
doorbell_error: usage: sb [-h] [--json] {start,delegate,…}
                sb: error: argu…
```

`collector.ring_doorbell` runs `shutil.which("sb")`. The board pane's PATH is whatever
herdr gave it — I read it off the process: it contains `/Users/andrew/.local/bin` and does
**not** contain the clone's `bin`. So the doorbell ran the installed `main` build, which
has no `flush` verb. `_pin_sb` runs for `delegate` and `restore`; it never touches the
board pane, so the pin does not cover the one process that rings.

### 3.3 The control that isolates it to that one line

I killed the clone's collector **by pid** and started the same module by hand with the
clone's `bin` first on PATH, cwd unchanged, everything else identical:

| time | what |
|---|---|
| 03:13:41 | collector's first doorbell — `doorbell_error: None` |
| 03:13:41 | all five messages `delivered_at` set |
| 03:13:49 | `pa3-lead` had read them (`read_at`) |
| 03:14:00 | it went on with its task and ran `sb block` |

A parent genuinely woken by its children's reports, no heartbeat, no human. So: **one
environment fact, the `sb` on the board pane's PATH, is the whole of what stands between
today and this criterion.**

### 3.4 What the doorbell depends on, stated plainly

1. **A board must be open somewhere.** Unchanged and structural — `ring_doorbell` is
   called only from `collector.tick`, and only `board.py` stamps `panel/demand`. A fan-out
   watched from a plain terminal is still silent. This is worth knowing before calling
   phase 1 done: the wake-up is a property of a window being open.
2. **That board's Python must have the doorbell** — now satisfied for a branch's own
   fan-out, thanks to the fork base.
3. **The `sb` on that board pane's PATH must have `flush`** — i.e. the *installed* build,
   machine-wide. Not satisfied on any checkout that is not installed, and the pin cannot
   help. Once `phase-1` is the main checkout this resolves itself; until then the doorbell
   cannot be exercised by the branch that contains it, except by hand.

---

## 4. Cleanup always explains itself — PASS

Every refusal I could reach names itself, and the wording is specific rather than generic:

```
refused pa3-lead:  blocked, not finished — it has not reported an end
refused pa3-w1:    working, not finished — it has not reported an end
refused pa3-w2:    unread mail it could still read
refused pa3-ra:    already closed
refused role X:    role X is kept, not closed (--include-kept)
sb cleanup pa3-lead → sb: still working underneath: pa3-lead → pa3-w1. Close them first …
sb cleanup pa3-nosuch → sb: not yours to clean up, or no such agent: pa3-nosuch
sb cleanup --force  → sb: --force needs the name of the agent to close: it lifts every
                       safety gate, so it is never a sweep
```

`--json` carries `{"closed": [...], "refused": [{"name","reason"}]}` in every case. A
blocked agent is now correctly reported as `blocked`, not (as in run 1) as `working`.

**Two silences.** Both follow from `cli.py`'s `if names.refused and (args.name or not
names)` and both were flagged in run 2 §4; I confirm them and add the second:

- A sweep that closes at least one agent prints **no** refusals. Mine printed
  `closed: pa3-w3, pa3-w4, pa3-w5, pa3-w6` and said nothing about having refused
  `pa3-w2` — the one row that then needed `--force`.
- **`--dry-run` is silent the same way.** `sb cleanup --dry-run` printed
  `would close: pa3-ra, pa3-rb, pa3-rc` with no mention that `pa3-mainchild` would be
  refused. The command whose entire purpose is "tell me what will happen" does not
  mention what will not happen.

The "always" in the plan's wording is therefore not literally true. Somebody should decide
which was meant; on the code's own reading this passes.

---

## 5. A blocked agent stays blocked until Andrew answers — PASS

### 5.1 The block keeps the name

`herdr agent get pa3-lead` **succeeded** while the agent was blocked (`{"agent":"claude",
"name":"pa3-lead"}`). That is the fix: run 2 got `agent_not_found` at the same point.

### 5.2 Sibling mail does not cancel it

03:16:24 — `pa3-w1` (a sibling, on the branch build) sent ordinary mail. Event
`ring_held pa3-lead {"reason": "blocked"}`, message `delivered_at = NULL`, row still
`blocked`, still `<< BLOCKED` on `sb status --needs-me`. The collector's doorbell, firing
every 10 s throughout, also declined to ring it.

### 5.3 The human's answer arrives — end to end

Inside the clone my session has no agent row, so `sb` resolves me as `HUMAN` and my
`sb tell` is the real answer path, not a simulation.

```
$ ./bin/sb tell pa3-lead 'HUMAN ANSWER: use blue. …'
sent to pa3-lead                      ← no UNREACHABLE note
03:17:13  unblocked pa3-lead          ← no ring_failed anywhere
03:17:14  both held messages delivered_at set
03:17:18  read_at set — the agent read them and answered "blue"
```

This is the failure run 2 confirmed, now gone. Both halves of the criterion hold.

### 5.4 The two things the fix's author left, checked

- **`sb done` still evicts the name. Confirmed.** After reporting, `pa3-w2`…`pa3-w6` all
  answer `agent_not_found` to `herdr agent get` and appear in `agent list` in the reported
  shape `{"agent":"pa3-w2"}`. `pa3-w1` (never reported) and `pa3-lead` (blocked, then
  idle) keep `{"agent":"claude","name":…}`. So it is `sb done` specifically, and only it.
  §6.1 is what that now costs.
- **A pane-typed answer delivers but leaves the row blocked. Confirmed.** With `pa3-lead`
  blocked a second time, I typed the answer straight into its pane (`herdr pane run` +
  `enter`). The agent took it and replied "Got green" — and the store still said
  `blocked`, and `sb status --needs-me` still printed `pa3-lead … << BLOCKED` for an agent
  that had answered and moved on. **New, and mitigating:** a later `sb tell` from the
  human does clear it (delivered and read at 03:27:42–46, row back to `working`), so this
  is a stale row, not a trap.

---

## 6. Found this run, nobody has counted these

### 6.1 A finished agent's mail drives an endless ring loop — the worst of the new ones

`sb tell pa3-w2 'are you there?'` to an agent that had *reported done* (name evicted, pane
still open — the ordinary state, since `sb done` deliberately keeps the agent open):

```
sent to pa3-w2 (pa3-w2 mid-turn or blocked — will be rung when free)
```

It is neither mid-turn nor blocked and it will never be rung. What then happened:

```
03:27:42 … 03:28:53   21 × ring_failed pa3-w2 {"error":"[agent_not_found] …","reason":null}
```

one every ~6–10 s, indefinitely, each one a doorbell tick spawning an `sb flush`
subprocess plus a herdr call, for a message that can never land. It stopped only when I
closed the agent.

`broker._finished_and_unreachable` exists precisely to stop this — its docstring says so
in as many words. It did not fire. The reason is at `broker.py:3684-3685`: it asks
`_agent_states()` whether herdr still lists the name, and `Agent.from_json` falls back
`name or agent`, so the **evicted** row `{"agent":"pa3-w2"}` still yields the key
`pa3-w2`. The predicate reads "herdr still knows this name" from the very fallback
`_binding_lost` uses to prove the opposite.

Two consequences, both observed: the loop above, and `sb cleanup` refusing that row with
`unread mail it could still read` on every sweep until I used `--force` — the jammed row
the same comment says it prevents.

This is an **interaction**, and it is new: before the doorbell fired, nothing retried, so
the same defect cost nothing. It arrives with the doorbell working.

### 6.2 Held mail keeps the doorbell spawning processes

While `pa3-lead` was blocked with one message held, the collector's `doorbells` counter
went 1 → 6 in about fifty seconds: `ring_doorbell` gates only on "is anything
undelivered", and mail held for a blocked agent is undelivered by definition. A block
answered in an hour costs ~360 `sb flush` processes. Cheap each, unbounded in total.

### 6.3 `ForkFailed` is reachable, and reports well

Delegating from a *linked worktree* (rather than a clone) fails loudly and usefully — the
first time any run has reached this path live:

```
sb: herdr [fork_failed] pa3-mainchild could not be given a worktree of its own, so it was
not spawned — … [linked_worktree_source] New and open worktree actions start from the repo
parent workspace.. It is not being put in <the worktree> instead: that checkout is somebody
else's working copy. Fix the fork, or place the child deliberately with
`sb delegate --workspace <name>`
```

### 6.4 `sb status`'s UNDELIVERED blurb is still wrong for an unreachable agent

`… the doorbell rings when the agent next goes idle` was printed for `pa3-w2`, which was
already idle and could never be rung. Same class as run 1 §5.2, unfixed.

### 6.5 Somebody was typing into my agent's pane

At 03:20 the text `now call sb done with a summary of the whole probe` was sitting
unsubmitted in `pa3-lead`'s input box. I did not put it there. Run 2 recorded the same
thing (§0) with different words. It was never submitted and no result here depends on that
pane's input, but two runs in a row is not a coincidence worth ignoring — either a person
watches these panes, or something types into them.

---

## 7. Fork base — PASS, both directions

- **Parent on a branch.** All six forks logged
  `{"base": "phase-1", "base_fallback": null, "inherited": true, "dirty": 0}`, the herdr
  call was `worktree create --branch pa3-wN --base phase-1`, and every worker reported its
  own HEAD as `1ff9285` — the parent's tip, the commit containing all three fixes. Combined
  with the pin (§0) the children were not merely *on* the branch, they *ran* it.
- **Parent on `main`.** From a clone checked out on `main`, driven by the branch's `sb`:
  `{"base": "origin/main", "base_fallback": null, "inherited": false, "dirty": 0}`.
  Unchanged behaviour, as designed.

### Interactions between the three fixes

I looked for these specifically, since all three touch spawning.

- **Fork base × pin — works, and they compound.** The pin now pins children to code that
  contains the branch, which is the whole point; before, it faithfully pinned them to
  `origin/main`.
- **Fork base × doorbell — one gain, one gap.** The gain: the board a `delegate` opens now
  runs the branch's Python, so the elected collector has the doorbell at all (§3.1). The
  gap: the pin does not extend to that board pane, so the collector still shells out to
  the *installed* `sb`. A branch collector calling an installed `sb` is a version skew
  nobody owns — today it manifests as "the verb does not exist" (§3.2).
- **Block × doorbell — §6.2.** **`done` × doorbell — §6.1**, the sharp one.

---

## 8. What I did not test

- Whether Andrew's own `sb tell`, typed in his terminal against the **installed** build on
  the **live** fleet, behaves as §5.3 does. Same code path, same identity resolution, but
  I proved it in a clone.
- The spawn **retry** path (`SPAWN_ATTEMPTS`): no spawn needed a retry, again.
- `TaskUndelivered`: never raised — §2 is the case where it *should* have been and was not.
- Whether the two dropped prompts share the cause I infer in §2. n = 2, both the first
  spawn into a cold context; three warm spawns afterwards were fine. Treat the mechanism
  as a hypothesis and the failure as a fact.
- Anything about `sb restore` re-binding an evicted name — the block fix's author settled
  that (`restore` refuses), and I did not re-run it.

---

## 9. Verdict

**Phase 1 is not finished.** Three of the four criteria hold, and all three follow-up
fixes do what their authors say — the doorbell no longer crashes and has now been watched
to wake a parent, blocking is no longer a one-way door, and a child starts from its
parent's branch. What is left is two things:

1. **A fan-out still does not reliably start every agent it reports.** Two of ten spawns
   produced a live pane with no task and no work, and the caller was told it had
   delegated. That is the criterion's own sentence, failing, and it is the failure mode
   the delivery confirmation was written to end.
2. **The doorbell's last dependency is the machine's installed `sb`, not the branch's.**
   Everything else in that chain is fixed; the board's pane is the one place nothing pins.
   Also worth Andrew's explicit decision, since it is structural and not a bug: the
   wake-up only exists while a board is open.

Smaller, and cheap: §6.1 (a done agent's mail loops the doorbell forever and jams
`cleanup`), §4's `--dry-run` silence, §6.4's stale blurb.

---

## 10. Throwaway agents and teardown

Created: `pa3-lead`, `pa3-w1`–`pa3-w6` in clone `sb3`; `pa3-mainchild`, `pa3-ra`,
`pa3-rb`, `pa3-rc` in clone `sbmain`. Eleven, all inside isolated clones, none ever
visible in the live fleet's store. All closed with `sb cleanup` (`--force` for the two
that were refused); the two leftover herdr workspaces closed with `herdr workspace close
<id>`. `herdr workspace list` afterwards is byte-for-byte the pre-run baseline
(`switchboard`, `main-4`, `worker-2`, `main-5`, `accept-phase1`, `accept-phase1-3`).

The one collector I started by hand was killed **by pid**. No unscoped `pkill` was used;
the only pattern kill was `pkill -f pa3-watch.sh`, my own polling script, a name that
exists nowhere else. Both clones and their worktrees under `~/.herdr/worktrees/sb3` and
`~/.herdr/worktrees/sbmain` were deleted. The live fleet's collector and boards were
running before this and are running after it.
