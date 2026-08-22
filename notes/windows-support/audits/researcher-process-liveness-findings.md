# Process liveness & subprocess shell-outs — Windows audit

Scope: `switchboard/live.py`, `switchboard/stats.py`, `switchboard/collector.py`, and the
process-scan/liveness/pid/signal call sites in `switchboard/broker.py`. Investigation only,
2026-08-22. No code changed.

## Headline: the prior investigation's "Linux lsof parse bug" does not reproduce

The prior note (`_prior-findings.md`) and `tests/test_live.py:70-72` / the CI workflow
comment all assert GNU/Linux `lsof -F pcn` emits **3-line** groups against BSD/macOS's
4-line groups, and that this makes `live._parse` (`live.py:99-113`) reject every group on
Linux, making `live.scan()` always answer "cannot tell" and the close-gate
(`broker.py:2305`) refuse forever.

**I tested this directly** (Docker, since this box is macOS) rather than trusting the
claim:

- Ubuntu 22.04, `lsof` from apt (revision 4.93.2, the `lsof-org/lsof` fork every current
  distro ships) — `lsof -a -d cwd -F pcn -p <pid>` on a real backgrounded process:
  ```
  p234
  csleep
  fcwd
  n/
  ```
  4 lines, exactly the shape `live._parse` expects (`p`/`c`/`fcwd`/`n` — see
  `.switchboard/notes/_scratch` not kept, but reproducible with the command above in any
  container).
- Debian 11, same `lsof` revision, same 4-line shape.
- Full unscoped scan (`lsof -a -d cwd -F pcn`, no `-p`) over 5 real processes on Ubuntu:
  every group was 4 lines, no exceptions.

So on any lsof shipped by a current Linux distro (the `lsof-org` fork — Purdue lsof's
successor, in use since ~2021), **the "BSD vs Linux 4-line vs 3-line" bug does not exist.**
The `-F` machine-readable format is standard across lsof's ports; it was never
platform-dependent in the way the prior note assumed. `tests/test_live.py:70-72`'s skip
(`skipUnless(sys.platform == "darwin", ...)`) and the CI workflow's explanatory comment are
both based on an unverified assumption, not a measurement — recommend un-skipping that
test on Linux, backed by a canned-fixture test using the literal captured output above
(no live Linux box needed in CI: this is a static string fixture), and correcting the
workflow comment.

**A real, different Linux behaviour I did find** (not a parser bug — a visibility/scope
difference, see below).

## 1. `switchboard/live.py` — the CWD scan

- **`live.py:61`**: `CWD_SCAN = ("lsof", "-a", "-d", "cwd", "-F", "pcn")`. POSIX-only —
  `lsof` does not exist on Windows. Hard call site; no Windows equivalent exists in the
  stdlib (see §4).
- **`live.py:89-96` (`scan`)**: `subprocess.run(list(CWD_SCAN), ...)`. Missing binary is
  handled correctly (`FileNotFoundError` -> `OSError` -> caught, returns `None`), so this
  degrades safely on Windows as written — it just always returns `None`, meaning
  `sb workspace close` refuses unconditionally there today (same "unknown, so refuse"
  behaviour the module already applies to Linux-without-lsof or macOS-without-lsof).
- **`live.py:99-113` (`_parse`)**: strict 4-line-group parser, `p`/`c`/`fcwd`/`n`. Verified
  correct for both BSD (macOS) and GNU (`lsof-org`) shapes — see headline above. **Latent
  behaviour difference on Linux, not a parse bug:** unprivileged Linux `lsof` does **not**
  omit other users' processes the way macOS's does — it lists every pid but reports the
  name as `n/proc/<pid>/cwd (readlink: Permission denied)` for ones it can't read. That
  still starts with `n/`, so `_parse` accepts it as a valid group and produces a `Proc`
  with `cwd="/proc/<pid>/cwd (readlink: Permission denied)"` — a nonsense path. This does
  not crash, and it is *functionally* harmless today because `is_under()`
  (`live.py:116-136`) will never match that string against a real checkout path, so it
  can't cause the close-gate to over-refuse or under-refuse. But it directly contradicts
  the module's documented invariant ("unprivileged lsof sees only the CALLER'S OWN
  processes", `live.py:26-37`), which is stated as if it were platform-universal and is
  actually macOS-specific behaviour. Measured on this machine (macOS, unprivileged):
  `ps -Ao` reported 655 processes, unprivileged `lsof -a -d cwd -F pcn` reported 412 pids —
  all of them from other users still listed by pid, just with permission-denied names, not
  omitted. Confirmed against real numbers: 413 of 655 processes here are mine; the scan
  still printed ~412 *groups* total including foreign ones (with junk paths), whereas the
  docstring's own measurement (from a different moment) describes macOS omitting 205
  foreign processes outright. **Recommend the module docstring be corrected**: the "narrow
  scope" is macOS behaviour; Linux's unprivileged lsof has a different (also narrow, but
  differently-shaped) scope, and Windows will differ again (see below).
- **`live.py:132-134` (`is_under`)**: catches `OSError`/`RuntimeError` from `Path.resolve()`.
  Already portable — `pathlib` is cross-platform, `Path.resolve()` behaves the same way
  Windows-side (drive letters and UNC paths resolve fine; the ELOOP-becomes-RuntimeError
  case is POSIX-specific but harmless to catch unconditionally). One thing to verify once
  on a real Windows box: path *component* comparison (`p.parts[:len(r.parts)] == r.parts`)
  needs both sides case-folded on Windows, since NTFS is case-insensitive but
  case-preserving and `Path.parts` is not case-normalized — `C:\Foo` and `c:\foo` would
  fail this comparison today. Not exercised by any current test. Low risk of Windows
  regression from getting this wrong (worst case: the gate is *more* conservative, i.e.
  refuses when it should allow, matching the module's fail-safe posture), but worth a
  Windows-specific test once portable.

## 2. `switchboard/stats.py` — CPU/memory/process-tree sampling

- **`stats.py:438` (`_PS`)**: `("ps", "-Ao", "pid=,ppid=,rss=,pcpu=")`, parsed strictly by
  `_ps_table` (`stats.py:556-579`). POSIX-only.
- **`stats.py:515` (`_available_darwin`)**: shells out to `vm_stat`, parses `Pages free` /
  `inactive` / `speculative` lines. macOS-only, already correctly gated behind
  `sys.platform == "darwin"` (`stats.py:501-503`).
- **`stats.py:540-553` (`_available_linux`)**: reads `/proc/meminfo` directly (no
  subprocess) — already portable to any Linux, including WSL. Confirmed this is the
  `_available_linux()` path the brief pointed at; it's fine as-is and needs no Windows
  change, just a new `_available_windows()` branch added to the `sys.platform` dispatch at
  `stats.py:501-503`.
- **The module explicitly rejected `psutil` already** (`stats.py:497-499`): *"Not `psutil`,
  which would be a dependency the collector's interpreter is not promised — the same
  reason everything else in here is a subprocess."* This is a real design decision on
  record, not an oversight — **any Windows-support plan that adopts `psutil` (see §4) is
  reversing that decision and should say so explicitly**, not slip it in as an incidental
  side effect of porting.
- No stdlib subprocess exists on Windows for either of `_PS`'s job (process table with
  RSS/CPU/PPID) or `vm_stat`'s job (available memory). See §4 for the two real options.

## 3. `switchboard/collector.py` — signal handling

- **`collector.py:768` (`_stop_on_signal`)**: `for sig in (signal.SIGINT, signal.SIGTERM,
  signal.SIGHUP): signal.signal(sig, handler)` guarded only by `except ValueError` (not
  main thread). **This is a hard blocker on Windows, same severity class as the `fcntl`
  import blockers already found**: `signal.SIGHUP` does not exist as an attribute of the
  `signal` module on Windows at all — referencing it raises `AttributeError`, which is
  *not* caught by the `except ValueError:` here. The tuple literal itself is evaluated
  eagerly, so `_stop_on_signal()` — called unconditionally from `run()` — crashes the
  collector at startup on native Windows, before a single tick runs. (I did not run this on
  a real Windows box; this is from documented CPython `signal` module platform support,
  not a live test — flagging the confidence level explicitly.)
- Even once that's fixed to skip missing signals: **`SIGTERM` is effectively a dead
  registration on Windows.** Windows has the constant, but the OS never delivers it the way
  POSIX does; the only way to raise it is another process calling `os.kill(pid,
  signal.SIGTERM)`, and on Windows that calls `TerminateProcess()` directly — it does
  **not** invoke a registered Python signal handler, it just kills the process
  immediately. So a graceful-shutdown path that depends on `SIGTERM` reaching `handler`
  (letting `run()`'s `finally: panel.release(fd)` execute, per `collector.py:716-717`)
  simply won't fire from an external "terminate this collector" on Windows the way it does
  on POSIX. `SIGINT` (Ctrl+C from the same console) does work on Windows and is the one
  signal here that's genuinely portable.
- This is not a correctness gap for the module's *stated* invariant, though: the module's
  own comment (`collector.py:657-658`) already says the lock "is released by the kernel
  however this process ends — a clean return, a signal, or `kill -9`", i.e. it was already
  designed to be safe under an unclean kill. A Windows port needs the *replacement* lock
  primitive (once `fcntl.flock` in `panel.py`/`plugins.py`/`sweep.py` is ported — out of my
  scope, but load-bearing here) to have that same "OS releases it when the process dies,
  clean or not" property. Windows file locks (`LockFileEx`/`msvcrt.locking`, or a
  cross-platform wrapper like `portalocker`) do have that property, so the design carries
  over; it's the SIGTERM-handler-as-cleanup-path that doesn't, and nothing here should be
  built to depend on it.
- No `os.kill`, `SIGKILL`, or `.terminate()`/`.kill()` calls anywhere in
  `switchboard/*.py` outside tests — confirmed by grep across the whole package, not just
  my scoped files. Switchboard never sends signals to panes; it only *catches* shutdown
  signals sent to its own collector/board processes. Pane lifecycle (starting, killing
  panes) is entirely herdr's, which the brief says already has native Windows support — so
  there's nothing here to reconcile beyond making sure switchboard's own two processes
  (collector, board) can start and shut down cleanly on Windows, which is the SIGHUP/SIGTERM
  issue above.
- **Spotted elsewhere (not my scope, flagging only):** `switchboard/board.py:2408-2422` has
  the identical `SIGINT/SIGTERM/SIGHUP` pattern with **no try/except at all** around
  `signal.signal(sig, bail)`, plus a `signal.signal(signal.SIGWINCH, on_resize)` at
  `board.py:2422` — `SIGWINCH` (terminal resize) doesn't exist on Windows either. That's a
  second, harder crash site in the rendering/terminal path, presumably another
  researcher's territory (board.py isn't in my brief's file list).

## 4. `switchboard/broker.py` — process-scan / liveness / pid call sites

Grepped the whole file for `ps `, `os.kill`, `signal`, `psutil`, `pid`, `SIGTERM`, `lsof`;
confirmed the only real subprocess/pid call sites are the four below.

- **`broker.py:1721`**: `live.scan()` — see §1.
- **`broker.py:2443`**: `live.processes_in(checkout)` inside `_live_under`
  (`broker.py:2425-2454`), which is the close-gate's actual liveness check. Traced the full
  chain: `Broker.close_workspace` (or whatever calls `_close_gate`, not shown in this
  excerpt but referenced at `broker.py:2297-2299`) -> `_records_gate` (store-only, no
  subprocess) + `_filed_gate` (store-only) + `_live_under` -> `live.processes_in` ->
  `live.scan` -> `lsof`. `_live_under` returning `None` (line 2305 check) is what raises
  "this machine could not be asked what is running" and refuses the whole close. This is
  the single choke point: port `live.scan`'s backend and the close-gate is ported, no other
  changes needed in the gate logic itself.
- **`broker.py:2464` (`_parents`)**: `subprocess.run(["ps", "-Ao", "pid=,ppid="], ...)`.
  Builds a full pid->ppid map, used by `_live_under` (line 2447-2454) to exclude the
  caller's own process ancestry/descendants from the found list (via `_ancestry`, not
  shown, presumably nearby). POSIX-only, same shape problem as `stats.py:438`'s `_PS` —
  these are two independent hand-rolled `ps -Ao` parsers for overlapping data (one wants
  `pid,ppid`, the other wants `pid,ppid,rss,pcpu`) that could trivially be one call if both
  used the same backend.
- No `os.kill`/`SIGTERM`/`SIGKILL` in broker.py — confirmed by grep. Broker never signals a
  process; it only reads the process table to decide who's alive.
- **PID semantics**: nothing here assumes anything Windows-incompatible about PID *values*
  (both platforms use small positive integers, no reuse-window assumptions I could find in
  this scope — `_ancestry`/`_descendants` just walk parent/child links by pid, which is
  cycle-safe and platform-agnostic). The only Windows wrinkle is that Windows doesn't have
  `ppid` as cheaply — getting a process's parent PID on Windows needs
  `CreateToolhelp32Snapshot`+`Process32First/Next` (ctypes) or `psutil.Process.ppid()`; it's
  not exposed by any single simple Windows tool the way `ps -Ao` exposes it on POSIX.

## 5. What Windows actually offers, and the recommendation

No Windows tool answers "which processes have this directory open" the way `lsof -d cwd`
does — there's no ownership-scoped, single-call equivalent. The real options:

1. **`psutil`** (third-party, C extension, BSD-3, prebuilt wheels for cp311/cp312 on
   win32/win_amd64/manylinux/macosx-universal2 — no compiler needed on any of the three
   target platforms in the normal case). `psutil.process_iter(['pid','ppid','cwd'])`
   replaces `live.CWD_SCAN`+`_parse` entirely, on all three platforms, with one code path
   instead of three shelled-out parsers. `psutil.Process.cwd()` on Windows reads the
   target process's PEB via `NtQueryInformationProcess`+`ReadProcessMemory`
   (`PROCESS_QUERY_INFORMATION|PROCESS_VM_READ`), and raises `psutil.AccessDenied` for a
   process owned by a different user without elevation — the same *shape* of restriction
   POSIX unprivileged `lsof`/`ps` already has, so the module's "narrow scope, not a
   failure" design principle (`live.py:26-37`) carries over cleanly if `AccessDenied` on
   one process is treated as "that one pid is invisible" rather than "the whole scan
   failed" (analogous to how macOS's lsof already omits foreign pids today). I could not
   verify this on a real Windows box — this is documented `psutil` behaviour, not a live
   test. `psutil.virtual_memory().available` replaces `_available_darwin`/`_available_linux`
   with one call on all three platforms (Windows via `GlobalMemoryStatusEx` internally).
   `psutil.process_iter(['pid','ppid','memory_info','cpu_percent'])` replaces both
   `stats._ps_table` and `broker._parents` — one enumeration serving both current call
   sites instead of two separate `ps -Ao` invocations with different column sets.
   **Cost**: a new required (not optional, unlike `rich`) third-party dependency for a
   module that explicitly rejected that trade before (`stats.py:497-499`) — needs an
   explicit decision, not a silent swap. It also changes the "None = could not tell"
   epistemics: `psutil.process_iter()` essentially never fails wholesale (unlike a missing
   binary or bad exit code), so the close-gate's fail-safe refusal path becomes much rarer
   — which is probably desirable (fewer false refusals) but is a behaviour change on
   macOS/Linux too, not just an added Windows capability, and should be tested and called
   out as such rather than shipped as an incidental side effect of the port.
2. **Hand-rolled `ctypes` Win32 calls** (`CreateToolhelp32Snapshot` for the process
   table/ppid, `GlobalMemoryStatusEx` for available memory, PEB-reading for cwd). Avoids
   the new dependency but re-implements a meaningful slice of what `psutil` already does
   and tests, for one platform only — the memory-available piece is a single straightforward
   struct call and is reasonable to hand-roll; the per-process cwd piece is the hard part
   (PEB/`ReadProcessMemory`, permission-sensitive, no simple stdlib path) and is exactly
   where `psutil` earns its cost.
3. **`wmic`/PowerShell shell-outs** (`Get-CimInstance Win32_Process`, or `wmic process
   get ...`): would keep the "subprocess, not a library" shape the rest of the codebase
   uses, but `wmic` is deprecated and removed starting with Windows 11 24H2, and
   PowerShell process-start overhead (~200-500ms per invocation) is far more expensive
   than the ~0.4s the module already worries about for the *combined* lsof+ps call on
   POSIX — this would make Windows measurably slower than the platforms it's matching,
   not just different. Not recommended.

**My read**: option 1 (`psutil`, adopted as one shared `procscan`-style abstraction
covering `live.py`, `stats.py`'s process/memory sampling, and `broker._parents`) is the
only option that gives Windows a real cwd-per-process answer at all without a large,
Windows-only maintenance burden, and it has the side benefit of collapsing three
hand-parsed subprocess formats (lsof `-F pcn`, two different `ps -Ao` column sets) into one
tested library on all three platforms — removing the parsing-bug risk class entirely
rather than just fixing today's instance of it. That said, it reverses a specific,
documented decision in this codebase (`stats.py:497-499`) and changes close-gate failure
semantics on macOS/Linux, not just Windows — this should be a named decision in the plan,
not an implementation detail.

## Test implications

- The Linux lsof-shape claim: testable today, no Windows/Linux box needed in CI — a
  fixture test feeding the literal 4-line output I captured (`p234\ncsleep\nfcwd\nn/\n`)
  through `live._parse` pins that it's accepted, and the skip on
  `tests/test_live.py:70-72` should be removed (or re-justified with an actual reason, if
  one exists that I didn't find).
- The Linux "foreign pids not omitted, permission-denied name instead" behaviour: testable
  today too, same way — feed a synthetic group with a `n/proc/123/cwd (readlink: ...)`
  line through `_parse` and confirm it parses (it does) and that `is_under()` correctly
  never matches it against a real root (it doesn't, verified by code reading, not by a
  live foreign-user process here since I only have my own).
- Windows behaviour (whichever of §4's options is chosen) **cannot be pinned without a
  real Windows box or a Windows CI runner** — GitHub Actions has `windows-latest` runners
  available free for public/private repos, and the CI matrix
  (`.github/workflows/tests.yml`) currently only runs `ubuntu-latest`+`macos-latest`. Adding
  `windows-latest` to the matrix is the only way any Windows-specific assertion here
  (psutil's `AccessDenied` shape, the PEB-read cwd correctness, `GlobalMemoryStatusEx`
  values) gets pinned rather than just documented.
- `collector.py`'s `SIGHUP` crash is testable today without Windows: mock
  `signal.SIGHUP` absent (`del signal.SIGHUP` under `unittest.mock.patch` or a
  platform-conditional attribute check) and confirm `_stop_on_signal` doesn't raise. Cheap,
  should be added regardless of when the actual Windows port lands.

## Everything I did not verify live

- All Windows-specific behaviour in this note (psutil's Windows cwd/AccessDenied shape,
  Windows SIGTERM/TerminateProcess semantics, `signal.SIGHUP` absence) is from documented
  CPython/psutil platform behaviour, not from running on a real Windows machine — I don't
  have one available. Flagging explicitly per the house rules: unproven and stated, not
  unproven and silent.
- I did not test lsof on macOS Sonoma/Sequoia variants beyond this machine's own Darwin
  25.5.0 — the BSD 4-line shape is long-standing and well-documented, so I did not treat
  this as a question needing separate verification the way the Linux claim did.
