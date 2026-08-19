# Round 3 — concurrency & thread-safety of the daemon-thread open (08bdcb7, on 6da8dc8)

Single lens: races, leaks, hangs in the new `open_tick` / `_open` / `open_note` mechanism
and its interaction with the curses loop. Path extraction, debounce, subprocess
crash-handling and injection are out of scope and not looked at.

**Verdict: good to go.** No data race, no leak, no hang, nothing swallowed. Three real
defects, all in status *reporting* rather than in the threading itself; one of them
(#1) is worth fixing before this is called done.

---

## 1. A second `oo` on a different agent is dropped, and the board implies otherwise

`switchboard/board.py:1855-1861`. `open_tick` refuses while a worker is alive and
**throws the name away** — `name` is never stored, never queued, never named in the
message.

Trigger: `oo` on A, then `oo` on B inside A's busy window.

Busy window is not short: `_editor` is called once for the worktree plus once per file,
`MAX_OPEN_FILES = 6` (board.py:1701), each with `timeout=_SUBPROCESS_TIMEOUT`, which
resolves to 10 on this machine. Worst case ≈70s during which every `oo` is refused.

Effect, measured:

```
$ python - <<'PY'   # open_report_files stubbed to sleep 1s and record its arg
run, m1 = board.open_tick("A", note, None)
run, m2 = board.open_tick("B", note, run)
PY
2. A -> opening A… | B -> still opening…
   subprocesses actually started for: ['A']
   mailbox says: ['-> A: opened']   <- names A, though B was the last request
```

Two ways this misleads:

- "still opening…" names nothing, so it reads as "your request is in progress" when the
  request was discarded. Nothing will ever open B.
- The line that arrives afterwards is `→ A: opened 3 file(s)` — a success line, arriving
  right after the user asked for B. Skimming, that is B confirmed.

Fix is small either way: name the agent in the refusal (`still opening A — try again`),
or hold the pending name and run it when the worker exits.

## 2. The open's answer loses to the sweep's, and to itself

`switchboard/board.py:2222-2227`. Both mailboxes drain into the same `msg`, sweep second:

```python
2222  if open_note:
2223      msg = open_note.pop()
2225  if sweep_note:
2226      msg = sweep_note.pop()
```

- An open finishing in the same ≤0.25s pass as a sweep line has its result silently
  discarded. Twice an hour, and the sweep is exactly the kind of slow thing that
  overlaps a `oo` pressed near the boundary.
- The same ordering, the other way: the drain at 2222 runs *after* the keypress handler
  at 2183, so a result line that landed since the last pass overwrites the fresh
  "opening B…" that the keypress just set. Self-corrects on the next line, but the
  keypress appears to do nothing.
- `pop()` takes the newest. If two entries ever coexist — worker A appends and dies, a
  keypress in the same pass starts B, B fails fast and appends before line 2222 — the
  older line is shown one frame *after* the newer. Narrow, cosmetic.

All three are the same shape: a background note may overwrite a note set this pass, and
the "one-slot mailbox" is really an unbounded list drained one item per pass, last-first.
`sweep_note` has the same shape, so this is inherited, not introduced — but the open path
fires on a keypress and so meets it far more often than something that runs twice an hour.

## 3. `t.start()` is the one uncaught raise on the new path

`switchboard/board.py:1859`, reached from `2183`. `RuntimeError: can't start a new thread`
under thread or memory exhaustion propagates out of `open_tick`, through the event loop,
past `except KeyboardInterrupt`, and ends the board — the exact failure class this commit
set out to close ("a setting must not be able to end the board").

Low probability, and `sweep_tick` (board.py:2071) has identical exposure, so it is not a
deviation from the pattern being mirrored. Recording it, not blocking on it.

---

## What I checked and found clean

**(a) No data race on the mailbox or the guard.** `open_note` is appended by exactly one
worker and popped by exactly one reader; both are single atomic list ops under the GIL,
with no read-modify-write on either side, so no update is lost or torn. The
`if open_note:` / `pop()` pair cannot race to `IndexError` because only the main loop
pops. `opening` is a `main()` local (board.py:2142) the worker never touches.

The worker shares no other mutable state: I read every callee of `open_report_files` —
`_inspect` (1917), `last_assistant_texts` (1889), `report_files` (1707), `_editor` (1943).
All take arguments or read module constants (`_EDITOR`, `_SUBPROCESS_TIMEOUT`,
`MAX_OPEN_FILES`); none write module or loop state. `where.name(snap.agents)` is resolved
on the main thread at 2184, before the thread starts, so the snapshot is never shared.

**(b) QUIT mid-open neither blocks nor leaks nor corrupts.** `q` raises KeyboardInterrupt
(2172) → `finally: restore()` (2104-2112) → return. The thread is a daemon and is never
joined, so exit is not delayed. It cannot corrupt the just-restored pane, because both
subprocess calls it makes use `capture_output=True` (1930, 1944) — nothing it runs
inherits the raw-mode terminal. The only cost is silent: the remaining `-r -g` tab opens
never happen. The editor window already spawned survives the board, which is the wanted
outcome.

**(c) The busy guard cannot get stuck true.** Two independent reasons:

- `_open` (1864) wraps the call in `except BaseException`, so the thread always reaches
  its end and dies. Verified live — a worker stubbed to raise `RuntimeError` left
  `note == ['open failed: kaboom']`, `is_alive() == False`, and the next `oo` returned
  `opening A…` rather than `still opening…`.
- The guard is `running.is_alive()` (1857), not a flag someone has to remember to clear.
  There is no code path that can leave it stale, only a thread that never exits.

And it cannot hang: every subprocess carries `timeout=10`, and on POSIX
`subprocess.run`'s timeout branch does `process.kill()` then `process.wait()` on the
direct child — *not* a second unbounded `communicate()` (that branch is Windows-only;
checked in this machine's CPython 3.11.5 source). So a `cursor` that wedges is killed,
not waited on forever. Bounded at ≈70s.

**(d) No thread pile-up.** The `is_alive()` guard admits exactly one worker; the burst
case is defect #1 above (dropped, not stacked), which is the intended trade.

**(e) Nothing swallowed.** `_open` catches `BaseException` and appends a line;
`open_report_files` catches its own subprocess failures (1831-1842) and returns a line.
Every terminal state of the worker produces exactly one mailbox entry. I could not find a
path where the user gets no feedback at all.

**vs. the pattern it claims to mirror — it does not omit a guard, it uses a better one.**
`Locator` (1487, 1493-1509) serialises with a `_busy: bool` set before `start()` and
cleared in a `finally:`; that is correct but stale-able in principle. `open_tick`'s
`is_alive()` cannot be left stale by any raise. `_sweep` (2075) has no busy guard at all —
slot arithmetic in `sweep_tick` serialises it instead. The only thing genuinely inherited
from `sweep_note` is the mailbox drain of defect #2.
