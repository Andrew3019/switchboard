# Phase 1 acceptance test, second run — in an isolated clone, on `fix-sb-path`

Run 2026-08-10 00:24–00:55 by agent `accept-phase1-2` (role qa). Nothing was fixed,
installed, pushed or merged; `main` untouched; the installed symlink untouched.

**Verdict: 2 of 4 criteria pass. The doorbell still fails, for a new and much simpler
reason. The block/name-binding defect is CONFIRMED, end to end, including the human's own
answer — which this run could test because inside the clone the tester *is* the human.**

| criterion | verdict |
|---|---|
| a fan-out of six agents starts six agents | **PASS** |
| every `done` wakes its parent without a heartbeat | **FAIL** — three independent causes, §3 |
| `cleanup` always explains itself | **PASS**, with one documented silence, §4 |
| a blocked agent stays blocked until Andrew answers | **PASS on the "stays blocked" half** (§5.1), but the way *out* is broken (§5.2) |

The single biggest finding is not on that list and is new: **`sb flush`, the doorbell's
one and only action, crashes every time the collector runs it**, because the collector
runs it with `cwd` set to the repo's `.git` directory, which is not a work tree (§3.3).
Two lines below that, a second new finding: **the `sb`-path pin does not put a delegated
agent on its parent's branch** — a child's checkout is always forked from `origin/main`,
and the pin faithfully pins the child to *that* build (§2).

---

## 0. The instance, and the proof it was the right one

`git clone /Users/andrew/Code/switchboard <scratch>/sbclone`, `git checkout fix-sb-path`
(`ae9e095`), driven only by the clone's own `./bin/sb`. Written below as `$C`.

- **Own store.** `$C/bin/sb doctor` run from inside the clone:
  `store <scratch>/sbclone/.git/agentflow/state.db`. `$C/bin/sb status` → `(no agents)`.
  The live fleet's `sb status` never listed any `pa2-*` agent.
- **Branch build, not the installed one.** The asymmetry is the hidden `flush` verb.
  `$C/bin/sb flush` (run from the clone root) → `rang nobody`. The PATH-installed
  `sb flush` → `argparse: invalid choice: 'flush'`.
- **The agents were on it too**, for the agents that mattered: the store logged
  `sb_pinned pa2-lead {"path": "<clone>/bin"}` and the same for `pa2-sib`. Both are
  top-level agents started with `sb start`; both ran the clone's build.

**One caveat readers must not skip.** `sb`'s store is resolved from the *process cwd*, not
from the binary's location. Running `$C/bin/sb doctor` from a shell sitting in Andrew's
worktree resolved to the **live** store (`/Users/andrew/Code/switchboard/.git/…`). I did
this once, at 00:24, and it ran one `sb flush` against the live store; it printed
`rang nobody`, so it delivered nothing. Every result below was produced from inside `$C`.
This is git-standard behaviour, not a defect, but it means "drive the clone's `./bin/sb`"
is only half the recipe — you must also be standing in the clone.

**Suite:** `/Users/andrew/anaconda3/bin/pytest -q` in the clone: **1748 passed in 115s**.

**Contamination noted, not resolved.** At 00:49 the text
`yes, wrap up — clean up the workers and report` was sitting unsubmitted in `pa2-lead`'s
input box. I did not put it there and cannot account for it; a person watching the pane is
the obvious explanation. It was never submitted and no result below depends on that pane's
input.

---

## 1. Six for six — PASS

`pa2-lead` (started with `sb start`, so on the clone's build) was given a task file
telling it to run six `sb delegate` calls. All six came up and all six reported:

| agent | delegated | `done` |
|---|---|---|
| pa2-w1 | 00:28:08 | 00:28:38 |
| pa2-w2 | 00:28:2x | 00:28:51 |
| pa2-w3 | 00:28:4x | 00:28:57 |
| pa2-w4 | 00:28:57 | 00:29:04 |
| pa2-w5 | 00:29:06 | 00:29:15 |
| pa2-w6 | 00:29:17 | 00:29:24 |

Six `delegate` events, six `done` events, six `[done] wN ok` messages, six distinct panes.
Whole fan-out: 76 s. No retry was needed, so the retry path is again **untested live**.

Loudness checks I could reach: a multi-line task is refused before spawn
(`sb: task must be a single line: herdr refuses any agent argument containing a newline`),
naming the checkout-relative fix. `ForkFailed` / `TaskUndelivered` again not reachable
without breaking herdr; not tested.

---

## 2. NEW — the `sb`-path pin does not put a delegated agent on the branch under test

The pin works exactly as its audit note says: before `agent start`, the pane is handed
`export PATH=<the agent's own checkout>/bin:"$PATH"` and the result is read back. Six
`sb_pinned` events, all confirmed.

**But a delegated agent's own checkout is a fresh worktree forked from `origin/main`.**
The store's own event says so:

```
worktree create --branch pa2-w1 --base origin/main …
sb_pinned pa2-w1 {"path": "/Users/andrew/.herdr/worktrees/sbclone/pa2-w1/bin"}
```

and that worktree is:

```
$ cd /Users/andrew/.herdr/worktrees/sbclone/pa2-w1
$ git rev-parse --abbrev-ref HEAD   → pa2-w1
$ git log --oneline -1              → f6bcd58   (= origin/main)
$ ./bin/sb flush                    → argparse: invalid choice: 'flush'
```

So every one of the six workers was pinned — to the **old** build. The base is
`git.base_branch = "origin/main"` in `defaults/settings.toml`, read by `_fork_base`; it is
never the parent's branch. The consequence is exactly the thing the pin was written to
end, relocated one level down: *a branch's fixes still cannot be acceptance-tested by the
agents that a branch's orchestrator delegates.* Only `sb start` agents — whose space is
laid over the checkout `sb` was run in — get the branch.

It also means the pin buys the live fleet nothing today: after it is installed, a
delegated child is pinned to its own `origin/main` worktree, which is the same code the
symlink already resolved to. It starts paying only once the change is on `origin/main`.

I am not proposing a fix; naming the effect is the finding.

---

## 3. Every `done` wakes its parent, with no heartbeat — FAIL

Three independent causes. Each was reproduced; the third is new and is the one that would
still bite after the other two were dealt with.

### 3.1 No board open → no collector → no doorbell

Unchanged and structural. `ring_doorbell` is only ever called from `collector.tick`; the
collector exits `panel.collector_idle_exit = 60 s` after the last renderer stops stamping
`panel/demand`, and only `board.py` stamps it. Observed: after `sb cleanup` closed the six
workers' boards at 00:32:36, the collector process was gone by 00:33:58.

### 3.2 With a board open, the collector that actually runs is old code

Every `sb delegate` opens a board beside the child (`board_open` events, one per worker),
and that board runs `python -m switchboard.board` with `PYTHONPATH` set to **the child's
worktree** — which §2 just showed is `origin/main`. The elected collector is therefore an
`origin/main` collector, and `origin/main` has no doorbell at all.

Measured, inside the clone, on the branch:

- Collector pid 94107, `cwd = /Users/andrew/.herdr/worktrees/sbclone/pa2-sleep`.
- Its published state block had keys
  `collected_at, errors, last_error, last_error_at, pid, polls, started_at, tick_ms, wrote_at`
  — none of `doorbells`, `last_doorbell`, `doorbell_error`.
- Message 12 (`DOORBELL PROBE 3`) sat `delivered_at = NULL` for **3 m 55 s** with the
  target idle, a board open, a live collector, and no `sb` run by anyone. Nothing rang.

This is the same signature the first acceptance run reported ("the running collector
predates the fix"), but the cause is different and does not go away with time: it is not a
stale process, it is *which checkout the board is opened in*.

### 3.3 NEW — even a branch collector cannot ring: `sb flush` crashes, every time

I then ran the branch's own collector by hand against the clone's store, so the doorbell
code was certainly current, and stamped `panel/demand` so it stayed up.

**(a) With the ordinary PATH** (`command -v sb` → `/Users/andrew/.local/bin/sb`):
doorbell fired once, `doorbell_error` =

```
usage: sb [-h] [--json] {start,delegate,ask,tell,…}
sb: error: argu…
```

i.e. the installed `main` build has no `flush` verb. The first run predicted this; it is
still true. Note the pin does **not** cover this case — it only touches spawned agent
panes, never the process that renders a board.

**(b) With the clone's `bin/` first on PATH**, so `sb` is the branch build:

```
doorbells 1
doorbell_error: Traceback (most recent call last):
  File "<clone>/bin/sb", line 5, in <module> …
```

Reproduced by hand, deterministically:

```
$ cd <clone>/.git && <clone>/bin/sb flush
RuntimeError: not inside a git repo: fatal: this operation must be run in a work tree
    (switchboard/store.py:76, from cli.py:591 repo = store.worktree_root())
$ cd <clone> && ./bin/sb flush
rang nobody
```

The cause is in `collector._run_doorbell`:

```python
cwd = str(db_path.parent.parent)
p = subprocess.run([sb, "flush"], cwd=cwd, …)
```

`db_path` is `<git-common-dir>/agentflow/state.db`, so `parent.parent` is the **`.git`
directory**, not the working tree. `cli.main` calls `store.worktree_root()` for every verb,
`git rev-parse --show-toplevel` fails inside `.git`, and the command dies before it does
anything. It is off by one directory. Nothing about it is specific to a clone: in the main
checkout `.git` is a plain directory too, so the doorbell would crash there identically.

So the doorbell has never once succeeded, on any machine, with any PATH.

**What I did not test:** whether a doorbell with the correct cwd actually delivers. It
cannot be tested without changing the code, which I was told not to do. What can be said
is that the command it would run is sound in isolation — `sb flush` from the clone root
exits 0 — and that `flush_pending` is covered by the passing suite. Treat "fix the cwd and
the doorbell works" as unproven.

---

## 4. Cleanup always explains itself — PASS

All against the clone's build.

```
$ ./bin/sb cleanup pa2-lead
closed: (nothing)
  refused pa2-lead: working, not finished — it has not reported an end

$ ./bin/sb cleanup            # second sweep, nothing left to close
closed: (nothing)
  refused pa2-lead: working, not finished — it has not reported an end
  refused pa2-w1: already closed
  … (w2–w6)

$ ./bin/sb cleanup --dry-run  # nothing to close
would close: (nothing)
  refused …                   # same list
```

`--json` carries `{"closed": [...], "refused": [{"name","reason"}]}` in every case.

**The one silence, and it is deliberate.** A sweep that closes at least one agent prints
*no* refusals — `cli.py:915`, `if names.refused and (args.name or not names)`, with a
comment explaining that listing the whole skipped fleet would bury the line that matters.
So the first sweep printed `closed: pa2-w1 … pa2-w6` and said nothing about having refused
`pa2-lead`. That is a defensible reading of the criterion, not a bug, but "always" in the
plan's wording is not literally true and somebody should decide which they meant.

The already-flagged noise problem is unchanged: a no-op sweep prints one `already closed`
line per closed agent in the caller's whole subtree.

---

## 5. A blocked agent stays blocked until Andrew answers

### 5.1 Sibling mail does not cancel a block — PASS, and this time honestly

Every participant was on the clone's build, so the first run's contamination (old-build
flushes cancelling blocks) cannot apply.

- 00:49:49 — `pa2-lead` ran `sb block "acceptance hold - waiting on the human"`.
  Store: `blocked`.
- 00:50:55 — `pa2-sib` (a second `sb start` agent, so also the clone's build) was told to
  `sb tell pa2-lead "sibling mail during a block"`.
- 00:51:00 — event `ring_held pa2-lead {"reason": "blocked"}`. Message 20 stayed
  `delivered_at = NULL`. `pa2-lead` was still `blocked` a minute later.

Item 1.9 does what it claims.

### 5.2 CONFIRMED — blocking costs the herdr name binding, and the human's answer is lost

This is the finding the brief asked me to confirm or refute. **Confirmed**, on this build,
with controls, and — new — carried all the way through a real human answer.

Before / after on the same agent:

```
# pa2-lead, idle, never blocked
$ herdr agent get pa2-lead   → {"result":{"agent":{… "agent_status":"done" …}}}

# after pa2-lead ran `sb block …`
$ herdr agent get pa2-lead   → {"error":{"code":"agent_not_found", …}}
```

Controls, at the same moment: `pa2-sib` and `pa2-sleep`, both idle, both never blocked,
both still resolved (`agent_status: idle` / `done`). So it is blocking that costs the
binding, not merely ending a turn.

Then the part the first run could not reach. **Inside the clone I am the human**:
`whoami` resolves by session id against the *clone's* store, my session has no row there,
so `sb` treats me as `HUMAN` and my `sb tell` is `answer=True` — the real human answer
path, not a simulation of it.

```
$ ./bin/sb tell pa2-lead 'HUMAN ANSWER: yes, this is the end of the probe. …'
sent to pa2-lead (pa2-lead UNREACHABLE — herdr has lost its name and the doorbell will
not ring again; the message is stored, but somebody has to go to its pane)
```

Store, same second (00:52:14):

```
unblocked   pa2-lead
ring_failed pa2-lead {"error":"[agent_not_found] agent target pa2-lead not found",
                      "reason":"name_binding_lost"}
```

and afterwards `pa2-lead` is `working`, off the blocked list, with **both** messages
(the sibling's and the human's answer) still `delivered_at = NULL, read_at = NULL`.

So the exact predicted failure, observed rather than inferred: the human answers, the
block clears, the agent never hears it. `sb status --needs-me` afterwards no longer says
`blocked` — it says `UNDELIVERED 3`, which is a different and much quieter thing.

What *does* work, and is worth keeping:

- The sender is warned, in the same breath, that the target is unreachable and somebody
  has to walk to its pane. That is phase 1's `unreachable` note, and it fired correctly on
  the human's answer.
- `_binding_lost` named it: the `ring_failed` event carries
  `"reason": "name_binding_lost"`.
- `sb interrupt pa2-lead "are you there?"` refuses loudly and correctly:
  *"nothing can be injected into its current turn — herdr answered [agent_not_found] …
  which is what a lost name binding looks like … if it has to land now, that needs a human
  in that pane."*

So item 1.6 diagnoses the failure well. It does not prevent it, and the failure is on the
one path Andrew has into a running fleet. **Blocking is currently a one-way door.**

### 5.3 What is still out of reach

Whether Andrew's answer typed **in his own terminal, against the installed build, on the
live fleet** behaves the same. I proved the code path with real `HUMAN` identity, but in a
clone. To close it on the live fleet somebody has to run, from Andrew's own shell, against
a live blocked agent: `sb tell <that agent> "…"` and then check `herdr agent get <that
agent>` and the message's `delivered_at`. It would prove nothing new about the code — the
identity resolution is the same — but it would rule out anything environment-specific.

I also did not test whether `sb restore` re-binds a name lost this way. That is the
obvious candidate for a way back and nobody has checked it.

---

## 6. Also found, nobody has counted these

1. **`sb flush` is run from `.git`** — §3.3. One directory, and the whole doorbell.
2. **`--base origin/main` versus the pin** — §2. A delegated agent can never be on its
   parent's branch, so a branch cannot be acceptance-tested by its own fan-out.
3. **The board's own `sb` is never pinned.** `_pin_sb` runs for `delegate` and `restore`
   (and `sb start`, observed). The pane that renders a board — and therefore the collector
   that spawns `sb flush` — inherits whatever PATH herdr gave it. §3.3(a).
4. **`sb cleanup --force` closes the workspace but leaves the checkout on disk.** After
   closing all eight `pa2-*` agents, `herdr workspace list` was clean, but
   `~/.herdr/worktrees/sbclone/` still held seven full worktrees, 30 MB. Plausibly
   deliberate (uncommitted work survives); recorded because a reader of `cleanup`'s output
   would not know.
5. **`sb doctor` reports the store of the cwd, not of the binary.** §0. It is the only
   command that tells you which instance you are driving, and it can quietly name a
   different repo's store while you are running a specific checkout's `sb`.
6. **The plan's own bar and `cleanup`'s deliberate silence disagree.** §4.

---

## 7. Throwaway agents and teardown

Created: `pa2-lead`, `pa2-w1`–`pa2-w6`, `pa2-sleep`, `pa2-sib` — nine, all inside the
isolated clone, none visible to the live fleet's `sb status`. All closed with
`$C/bin/sb cleanup … --force`; `herdr workspace list` afterwards contained no `pa2-*` and
no `sbclone` entry. Two collector processes I started by hand were killed. The clone
directory and its worktrees were deleted. The installed symlink, `main`, `BUILD-PLAN.md`
and `DESIGN-TRUTH.md` were not touched.

The known herdr leak behaved as `audit/isolated-instance.md` says it does: the clone's
panes appeared in the machine-wide `herdr workspace list` while they were alive.

**One mistake of mine, disclosed.** Tearing down, I ran `pkill -f switchboard.collector`,
which is not scoped to the clone — it also killed the **live** fleet's collector
(pid 41808 → its successor). A live board renderer re-elected a new one within seconds
(pid 1871, `cwd = /Users/andrew/Code/switchboard`, `sb doctor` → `1 up, 0 errors`), so the
live panel was stale for a few seconds and nothing else. No live agent, message or store
row was touched. Kill collectors by pid, not by pattern.
