# Adversarial review — lens: the zero-regression-to-macOS/Linux claim (D1 psutil priority)

Artifact: `notes/windows-support-plan.md` @ `d2c4807`, branch `lead-windows-support-plan`.
Reviewer: `reviewer-zero-regression`. Date 2026-08-22.

**Verdict: the zero-regression claim does NOT hold as written.** §5 says "The POSIX side of every
proposed change is a verbatim extraction of current code, so the no-regression claim for
macOS/Linux is high-confidence." That sentence is false for at least five of the proposed changes.
Two of them (F10/F11, and the CPU% half of F2/D1) change macOS behaviour *today*, on Andrew's own
machine, in ways the plan does not mention at all.

Everything below was run on this Mac (Darwin 25.5.0, `/Users/andrew/anaconda3/bin/python`,
psutil 5.9.0) unless marked INFERRED.

---

## 1. HIGH — F10/F11 `reconfigure(encoding="utf-8")` silently flips the error handler to `strict`

**Plan text:** F10 — "`sys.stdout.reconfigure(encoding="utf-8")` at board startup — **no platform
gate needed**". F11 — same for `sys.stdin` in the hook entry point. The whole encoding class is
labelled "Zero-risk on POSIX (it is what a UTF-8 locale already does)".

**What actually happens.** `TextIOWrapper.reconfigure(encoding=...)` with no `errors=` resets the
error handler to `strict`. Measured:

```
$ env | grep -i '^LANG\|^LC_'
LANG=C.UTF-8
LC_CTYPE=UTF-8
$ python -c "import sys;print(sys.stdout.encoding, sys.stdout.errors)"
utf-8 surrogateescape                     # <-- today, in Andrew's live env
>>> sys.stdout.reconfigure(encoding="utf-8"); sys.stdout.errors
'strict'                                  # <-- after F10
$ python -c "import sys;print(sys.stdin.encoding, sys.stdin.errors)"
utf-8 surrogateescape                     # <-- F11's side, same flip
```

CPython uses `surrogateescape` for stdio whenever the locale is `C`/`POSIX`/`C.UTF-8`. Confirmed
that it is locale-dependent and not universal:

```
$ env -u LC_CTYPE LANG=en_US.UTF-8 python3 -c "import sys;print(sys.stdout.errors)"  -> strict
$ env -u LC_CTYPE LANG=C.UTF-8     python3 -c "import sys;print(sys.stdout.errors)"  -> surrogateescape
```

`LANG=C.UTF-8` is what this repo's agent panes actually run under, so this is the live case, not a
corner.

**The macOS/Linux behaviour that changes.**
- `board.py:2333` (`sys.stdout.write("".join(out))`). A lone surrogate anywhere in the frame — the
  usual source is `os.fsdecode` on a path with undecodable bytes, reached through `Path.iterdir`
  and the checkout/workspace paths the board prints — prints today and raises `UnicodeEncodeError`
  after the change. The board is the primary UI and this is its single write.
- `bin/sb-stop-hook:28` / `bin/sb-activity-hook:27` (`hooks.run(sys.stdin.read())`). Same flip on
  the read side: a payload byte that round-trips through `surrogateescape` today raises
  `UnicodeDecodeError` after. Both scripts catch and return 0 — hooks fail open by design — so the
  **Stop gate silently stops firing on macOS** with nothing logged. That is precisely the failure
  mode F11 is written to *fix* on Windows, reintroduced on POSIX.

Caveat, stated rather than implied: I verified the error-handler flip, not that a lone surrogate
currently reaches either call site. I did not construct that end-to-end repro.

**Second defect, same line.** `reconfigure` is a `TextIOWrapper` method. Under captured stdout it
does not exist:

```
with contextlib.redirect_stdout(io.StringIO()):
    sys.stdout.reconfigure(encoding="utf-8")
AttributeError: '_io.StringIO' object has no attribute 'reconfigure'
```

An unguarded call at board startup crashes under any stdout capture (pytest's `capsys`,
`redirect_stdout`). This is an all-platform break, not a Windows one.

**Fix the plan needs:** pass `errors=` explicitly (`errors=sys.stdout.errors` to preserve, or a
deliberate documented choice), and guard the call with `getattr(sys.stdout, "reconfigure", None)`.
Delete "no platform gate needed" and "zero-risk on POSIX" as they stand.

**Disclosed?** No. The plan's §5 unproven-list does not contain it either.

---

## 2. HIGH — D1/F2: psutil has no equivalent of `ps pcpu`; the fleet CPU% number changes meaning

`stats.py:438` `_PS = ("ps", "-Ao", "pid=,ppid=,rss=,pcpu=")`, consumed at `stats.py:480`
(`cpu = sum(table[pid][2] ...)`). The docstring at `stats.py:454-457` documents the semantics **as
a thing shown on screen**: "`%CPU` from `ps` is not instantaneous. On macOS it is a decaying
average over up to a minute of real time, on Linux an average over the process's whole life."

psutil's nearest call is `Process.cpu_percent()`, which is a different quantity — CPU used *since
the previous call on that Process object*, and `0.0` on the first call. Measured:

```
me = psutil.Process(os.getpid())
me.cpu_percent()          -> 0.0        # first call, always
<0.3s of busy loop>
me.cpu_percent()          -> 100.0
ps -o pcpu= -p <same pid> -> 70.9       # what switchboard reports today
```

Consequences on macOS/Linux:
- The published number changes definition. 70.9 and 100.0 are not the same measurement.
- If `procscan` is stateless (fresh `Process` objects per sample, the obvious shape for a module
  serving three unrelated callers), **fleet CPU% is 0.0 forever** — every first call returns 0.0.
  Keeping it non-zero requires per-pid state retained across the collector's sample cadence
  (`stats.py:166`, behind `_PROC.get(...)`), which is a design constraint the plan does not name.

The plan treats `stats.py:438` as a straight swap (F2: "POSIX-only process/memory subprocesses →
D1"). CPU% is not mentioned anywhere in the document. **Not disclosed, not tested.**

---

## 3. HIGH/MED — D1: `_live_under`'s two-phase read is load-bearing; "one enumeration" destroys it

`broker.py:2443-2454`:

```python
found = live.processes_in(checkout)     # phase 1: lsof
...
parents = self._parents()               # phase 2: ps, deliberately AFTER
...
return [p for p in found if p.pid in parents and p.pid not in ours
        and mine not in _ancestry(p.pid, parents)]
```

The docstring at `broker.py:2437-2441` states the ordering is intentional: "the process table is
read AFTER the scan ... A pid the process table no longer knows has exited, and a process that has
exited is not in the directory." So `p.pid in parents` is a **liveness re-check** exploiting the
gap between two independent reads.

The plan's §2 primitive is `switchboard/procscan.py` — "**one enumeration** serving `live.scan`,
`stats` memory/process sampling, and `broker._parents`". If `found` and `parents` come from one
snapshot, `p.pid in parents` is vacuously true for every entry, the re-check disappears, and
processes that today drop out (they exited during the gap) now count against the close gate —
**new refusals on macOS for a directory that is genuinely empty**. Safe direction, but a real
change to the gate's answer, and the plan asserts the opposite ("the only semantic change is that
false refusals get rarer").

Related implementation hazard, measured. A parents map built from a per-process fetch that
discards `AccessDenied` loses 40% of the machine:

```
ps -Ao pid=,ppid=       -> 536 processes
psutil ppid via process_iter -> 536, 0 mismatches   # complete, if you only ask for ppid
psutil memory_info()    -> 320 ok, 213 AccessDenied # incomplete, if you ask for anything else
```

`_ancestry` (`broker.py:589-600`) walks up to pid 1 through root-owned parents. A map missing those
truncates the chain and the caller's own tree stops being excluded → the gate refuses to close a
workspace the caller is standing in. The plan must specify: build the ppid map from `ppid` alone,
and never from a combined fetch.

---

## 4. MED — D1: an empty-string cwd from psutil resolves to the broker's own cwd

`live._parse` (`live.py:106-107`) requires `name.startswith("n/")` — an absolute path. An empty or
relative cwd structurally cannot enter the current answer.

psutil has no such guarantee. And an empty cwd is not benign here:

```
Path('').resolve()  ->  '/Users/andrew/.herdr/worktrees/switchboard/lead-windows-support-plan'
os.getcwd()         ->  same
```

`is_under('', checkout)` (`live.py:132-136`) therefore returns **True** whenever the broker's own
cwd is under the checkout — which is the normal case for `sb workspace close` run from inside the
workspace. One empty-cwd process anywhere on the machine ⇒ permanent refusal.

macOS is safe today: a zombie raises `ZombieProcess`, verified —

```
p = subprocess.Popen(["/bin/sh","-c","exit 0"]); time.sleep(0.4)
psutil.Process(p.pid).status() -> 'zombie'
psutil.Process(p.pid).cwd()    -> ZombieProcess: PID still exists but it's a zombie
```

Linux `_pslinux.py:2006-2014` also raises (`NoSuchProcess`/`ZombieProcess`) rather than returning
`''`. So this is a latent trap rather than a demonstrated Linux break — but `procscan` must reject
any cwd that is not absolute, and the plan says nothing about validating psutil's output at all.
INFERRED for kernel threads / other psutil versions; I did not test on Linux.

---

## 5. MED/LOW — D1: `Proc.command` changes on macOS for ~6% of processes

lsof's `-F c` command field is truncated at 31 characters; psutil's `name()` is not, and on macOS
it falls back to a cmdline-derived name that can be entirely different. Measured, 321 processes:

```
command-name differs: 19 of 321
  lsof='VoiceMemosSettingsWidgetExtensi'  psutil='VoiceMemosSettingsWidgetExtension'
  lsof='Cursor Helper (Plugin)'           psutil='Cursor Helper (Plugin): extension-host (user) Unified Agent [1-1]'
  lsof='git-remote-http'                  psutil='git-remote-https'
```

Surfaces in two places a human reads:
- the close refusal at `broker.py:2312` (`f"{p.command} ({p.pid})"`),
- `sb workspace list`'s `live[]` payload (`_listed_workspace`, `broker.py:1777`).

Cosmetic, but it is user-visible macOS output changing, and any test pinning a command string
breaks. Not disclosed.

---

## 6. MED — F6 as written specifies a POSIX regression

Plan: "check for the `.cmd`/`.exe` shim's existence; invoke that path." The four sites are
`board.py:2217`, `collector.py:475`, `broker.py:415`, `plans/__init__.py:3573`, and all four use
`os.access(own, os.X_OK)` as the test for *this checkout has a runnable `sb`*, with
`shutil.which("sb")` as the fallback:

```python
sb = str(own) if os.access(own, os.X_OK) else shutil.which("sb")   # board.py:2217
return sb.parent if os.access(sb, os.X_OK) else None               # broker.py:415
```

Replacing the predicate with an existence check *unconditionally* changes POSIX: a `bin/sb` that
exists but is not executable (`core.fileMode=false` checkout, a copy onto a share, a tarball
export) today falls back to the installed `sb`, and afterwards is returned and then fails at
`subprocess.run` with `PermissionError`. At `broker.py:415` that is worse than a failure — it pins
a PATH dir whose `sb` cannot run, i.e. `SbUnpinned` on every macOS spawn.

The fix has to be `os.name == "nt"`-gated with `os.access(X_OK)` kept verbatim on POSIX. The plan's
fix column does not say that.

---

## 7. MED — B5's POSIX path stops being unconditional and starts depending on an unproven fact

`broker.py:3341-3356` today emits one command string with no detection of anything. The plan
branches it "by pane shell family (cmd/pwsh/posix)", and Phase 3 concedes the input is unverified:
"Needs a herdr-reported 'what shell does this pane run' fact — **confirm herdr's API exposes it**".

So the macOS path changes from "always this string" to "this string when a new, unconfirmed herdr
query answers `posix`". No default is stated. If the fact is unavailable — an older herdr, an
adapter that does not implement it — and the code falls anywhere but POSIX, every spawn on macOS
times out into `SbUnpinned`. The plan's own §4 test ("the POSIX branch is byte-identical to
today") pins the string but not the *dispatch*.

Needs one sentence in the plan: absence of the herdr fact means POSIX, and a test for that.

---

## 8. MED — B1's lock-site list is wrong; `panel.py:478` is missing

The plan says "6 sites: `plugins.py:687`, `sweep.py:308`, `panel.py:435/453/474`, `broker.py:2863`,
and `defaults/plugins/plans/__init__.py:2869`" — that enumeration is 7 items called 6, and the
actual grep finds one more:

```
$ grep -n 'flock' switchboard/*.py defaults/plugins/plans/__init__.py
switchboard/plugins.py:687   fcntl.flock(fd, fcntl.LOCK_EX)
switchboard/sweep.py:308     fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
switchboard/panel.py:435     fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
switchboard/panel.py:453     fcntl.flock(fd, fcntl.LOCK_UN)
switchboard/panel.py:474     fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
switchboard/panel.py:478     fcntl.flock(fd, fcntl.LOCK_UN)      # <-- not in the plan
switchboard/broker.py:2863   fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
defaults/plugins/plans/__init__.py:2869  fcntl.flock(fd, fcntl.LOCK_EX)
```

`panel.py:478` is `collector_running`'s release (`panel.py:458-481`). Convert the other three and
`import fcntl` still has to stay at `panel.py:69` — so B1 is not done and Phase 1's "imports
succeed on Windows" exit criterion still fails on `panel.py`. Not a macOS regression; a hole in the
plan's own inventory, in the same class as the `defaults/` miss round 1 found.

Note in the plan's favour: the proposed signature `lock(fd, *, blocking)` / `unlock(fd)` keeps the
fd with the caller, which is what `panel.acquire`'s "the fd IS the lock" contract
(`panel.py:426-430`) requires. A path-taking API would have been a real POSIX regression; this one
is not.

---

## What held under attack (checked, no finding)

Reported because the brief asked me to attack these specifically and they survived:

- **`broker._parents` → psutil is behaviour-preserving on macOS.** `ps -Ao pid=,ppid=` and
  `psutil.process_iter(['pid','ppid'])` both returned 536 processes with **0 ppid mismatches** and
  a 1-process symmetric difference (the transient `ps` child). ppid is readable for foreign
  processes; no `AccessDenied` at all on that attribute.
- **psutil's cwd set matches lsof's on macOS, including the scope narrowing.** lsof 325 procs,
  psutil 323 with a readable cwd, **0 cwd strings differing**, 0 pids psutil had that lsof did not.
  The two lsof-only pids are `lsof` itself and its child. psutil's 213 `AccessDenied` reproduce
  lsof's documented own-user-only scope (`live.py:25-37`) rather than widening it.
- **RSS is the same number.** `ps -o rss=` and `psutil.memory_info().rss` both gave 25952 KB for
  the same pid. The brief's RSS-vs-USS worry does not apply.
- **`available` memory is the same number on macOS.** `stats._available_darwin()` = 1438334976,
  `psutil.virtual_memory().available` = 1439301632 — 0.9 MB apart, i.e. sampling skew, not a
  definition change. The brief's "free vs available" worry does not hold; psutil's macOS
  `available` is `inactive + free` and matches the `free + inactive + speculative` assembly at
  `stats.py:509`.
- **F9 and F12 really are POSIX no-ops.** Under this repo's `LANG=C.UTF-8`,
  `locale.getpreferredencoding(False)` is `UTF-8` and `read_text`/`subprocess(text=True)` already
  use `errors='strict'`, so adding `encoding="utf-8"` changes nothing. (This is exactly why F10/F11
  are different: those touch `sys.std*`, which is the one place CPython does *not* use strict.)
- **F7 (shlex) and F3 (select) are stated as clean forks** — "keep `shlex.quote` for POSIX",
  "Windows branch: `msvcrt.kbhit()`". No shared-path change.
- **The `lockfile` API keeps the fd with the caller** — see the note at the end of §8.

---

## Bottom line

Zero regression to macOS/Linux does **not** hold as the plan is written. §5's blanket sentence
should be replaced with a per-item statement, and §2/§4 need: an explicit `errors=` on both
`reconfigure` calls plus a capture guard (#1), a decision and a test for fleet CPU% (#2), a written
rule that `procscan` keeps the scan and the ppid read as two separate reads in that order (#3),
absolute-path validation on psutil cwd (#4), `os.name`-gating on F6 (#6), a stated POSIX default
for B5's shell-family dispatch (#7), and `panel.py:478` added to B1 (#8).
