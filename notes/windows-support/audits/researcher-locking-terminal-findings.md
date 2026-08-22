# Locking / terminal / DB-concurrency audit for native Windows support

Scope: fcntl/flock, termios/tty raw-mode input, sqlite concurrency in store.py.
Read-only audit, no code changed. Python 3.11/3.12 assumed.

## 1. All `fcntl`/`flock` sites (five, not four — prior work missed one comment-only
   reference at broker.py:6039 which is NOT a lock site, it's a design note explaining
   why that path does NOT use fcntl)

| # | Import | Lock call | Mode | Protects | Cross-process? |
|---|---|---|---|---|---|
| 1 | `plugins.py:62` | `plugins.py:687` `locked()` | `LOCK_EX` (blocking) | per-plugin-state-dir `.lock`, held for one handler call | yes |
| 2 | `sweep.py:44` | `sweep.py:308` `claim()` | `LOCK_EX\|LOCK_NB` | `slot.lock` — board's 30-min sweep-slot election | yes |
| 3 | `panel.py:69` | `panel.py:435` `acquire()` | `LOCK_EX\|LOCK_NB` | `panel/…/lock` — collector election, fd held for the collector's whole life | yes |
| 3b | same | `panel.py:453` `release()` | `LOCK_UN` | releases #3 | yes |
| 3c | same | `panel.py:474` `collector_running()` | `LOCK_EX\|LOCK_NB` then immediate `LOCK_UN` | probe-only, used by `sb doctor` | yes |
| 4 | `broker.py:33` | `broker.py:2863` `_fork_lock()` | `LOCK_EX\|LOCK_NB`, polled in a loop up to `FORK_LOCK_WAIT` | `fork.lock` under `.git/agentflow` — serializes concurrent `git worktree add` during a fan-out spawn | yes, and specifically cross-worktree (same physical `.git`) |

All five are **whole-file, advisory, cross-process** locks on a dedicated zero-byte
lock file (never on the data file itself — the data file is always rewritten
separately via `tmp + os.replace`, e.g. `panel.py:259`, doc'd at `plugins.py:675`).
None are cross-thread-only; none rely on shared locks (`LOCK_SH` is never used — every
site is exclusive-only, single-writer). This matters for the Windows port: **byte-range
mandatory locking on Windows never collides with the separate data-file rewrite**,
because nothing ever locks the data file, only the empty sentinel `.lock` file next to
it.

Two behaviours are explicitly *load-bearing* in the code's own comments and both
depend on POSIX-only-documented semantics that Windows happens to share, but which the
port must not assume without checking:

- **"closing releases the lock, and the kernel does this on `kill -9` too"**
  (`panel.py:428`, `broker.py:2842`, `plugins.py:690`, `broker.py:2880`). On Windows,
  `LockFileEx`/`msvcrt.locking()` byte-range locks are likewise released automatically
  when the owning handle is closed or the process exits — this property **does**
  transfer. No stale-lock cleanup logic needs to be invented for Windows.
- **No lock is ever held across a slow operation except #4, which is explicitly
  bounded and treats timeout as a soft "proceed anyway"** — so blocking-forever failure
  modes are not a new risk on Windows.

### Second latent-bug check (the brief asks for a Linux-analogue of the `lsof` bug)
None of the five lock sites has a POSIX/Linux-specific latent bug — they're all plain
`flock`, uniform behavior on macOS and Linux. I did not find a second bug in this area
comparable to the `lsof` one; that one is isolated to `live.py` (outside this scope).

## 2. Cross-platform locking primitive — recommendation

**Recommend a small internal abstraction, not `portalocker`.** Concretely, add
`switchboard/lockfile.py` with two functions used by all five sites:

```python
def lock(fd: int, *, blocking: bool) -> bool:   # True if acquired
def unlock(fd: int) -> None
```

POSIX branch: exactly today's `fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else
fcntl.LOCK_NB))`, catching `OSError` for the non-blocking case — a straight
extraction of what's already inline five times, zero behavior change.

Windows branch: `msvcrt.locking(fd, msvcrt.LK_LOCK or LK_NBLCK, 1)` at offset 0. Two
things a Windows implementation must get right that a naive port would miss:

- `msvcrt.locking()` locks **`nbytes` bytes starting at the current file position**,
  not the whole file — every call site must first `os.lseek(fd, 0, os.SEEK_SET)` (or
  the abstraction does it internally) so all five sites lock the *same* byte range and
  actually contend with each other.
- Locking works on a 0-byte file (all five `.lock` files are created via
  `os.O_CREAT` with no explicit size, i.e., empty). Windows `LockFileEx` permits
  locking a range beyond current EOF, which is the standard trick lock libraries
  (including `portalocker`) rely on — but it's the one thing worth an explicit unit
  test in the shim rather than assuming it just works, since I have not run this on an
  actual Windows box.
- Unlocking (`LOCK_UN`) is explicit on Windows the same way it already is at
  `panel.py:453`/`478` — no change needed there, just route through the shim.

Why not `portalocker`: it's a well-tested wrapper around exactly this, and would be
the safer choice if the team is willing to add a second dependency. But the project's
stated posture is "only third-party dep is `rich`, and it's optional" — a ~40-line
internal shim covers 100% of what's actually used here (whole-file exclusive lock,
blocking or non-blocking, no shared locks, no locked-region introspection), so it's
proportionate to add nothing rather than a dependency for five call sites. If the team
already leans toward accepting deps for the Windows port (e.g. for keyboard input,
see §3), `portalocker` becomes more attractive purely to keep the total surface area
of hand-written Windows-only code smaller — that's a judgment call for whoever owns
the port, not a technical blocker either way.

**No POSIX-regression risk**: the POSIX branch of the shim is a byte-identical
extraction of current code, and the five call sites become one-line calls into it.

### The one real semantic gap: mandatory vs advisory
`flock` is advisory — nothing on POSIX stops a process from `open()`+`read()`+`write()`
on the locked file while ignoring the lock. Windows locking is **mandatory**: the OS
itself will fail a conflicting read/write from another process/handle with a sharing
violation, even if that other process never calls `msvcrt.locking()`. As established
above, this is *harmless here* because nothing else ever opens the `.lock` files for
plain I/O other than the owner writing its own pid (`panel.py:443`, always by the lock
holder itself, which is permitted). But it is a constraint the port must preserve
going forward: **never add code that reads a `.lock` file's contents from a second
process without acquiring the lock first** — that would work by accident on POSIX and
throw `PermissionError` on Windows. Worth a one-line comment in the new shim so a
future author doesn't add exactly that.

## 3. Raw-mode keyboard/mouse input — `board.py`

This is the deepest single piece of the port, bigger than the locking work.

### Current architecture (`board.py:2380` `main()`)
- `import termios` (`board.py:55`) / `import tty` (`board.py:58`) at **module level** —
  this alone means `board.py` cannot be imported at all on Windows, not just that
  interactive mode degrades. And **`richboard.py:43` does `from . import board`**, so
  richboard is *also* unimportable on Windows even though richboard's own code never
  touches termios (`grep` confirms zero termios/fcntl references in richboard.py
  itself — it's purely collateral damage from the module-level import).
- Save/restore: `termios.tcgetattr(fd)` (`board.py:2395`) once at startup,
  `tty.setraw(fd)` (`board.py:2452`) to enter raw mode, `termios.tcsetattr(fd,
  TCSADRAIN, saved)` (`board.py:2406`) to restore — on normal exit, and inside signal
  handlers for `SIGINT`/`SIGTERM`/`SIGHUP` (`board.py:2414-2415`) so a killed pane
  isn't left in raw mode with mouse-reporting on.
- Read loop (`board.py:2463` onward): `select.select([fd], [], [], 0.25)`
  (`board.py:2473`) — a 250ms poll so the loop can also service two background
  mailboxes (`sweep_note`, `open_note`) and redraw on `SIGWINCH`
  (`board.py:2422`/`on_resize`) — then `os.read(fd, 1024)` (`board.py:2475`), decoded
  as UTF-8, fed through `parse_sgr()` (`board.py:139`) which parses **xterm SGR mouse
  mode** (`MOUSE_ON = "\033[?1000h\033[?1006h"`, `board.py:71`) and other ANSI escape
  sequences out of the raw byte stream.

### Why each piece breaks on Windows, one at a time
- `termios`/`tty`: modules don't exist on Windows at all (not degraded, `ImportError`
  at module load). No ConPTY workaround changes this — Windows never implements the
  POSIX termios API, ConPTY or not.
- `select.select()` on a non-socket fd: Windows' `select()` only accepts socket
  objects/handles. A stdin console fd is not a socket, so this call would raise
  `OSError`/`select.error` immediately even if termios were somehow stubbed out.
- `os.read(fd, 1024)` on a Windows console: doesn't give you the same thing. Windows
  console input is fundamentally event-based (`ReadConsoleInputW`), not a byte stream,
  *unless* you opt the console into VT (ANSI) mode.
- `signal.SIGWINCH`: doesn't exist on Windows (`AttributeError` at
  `signal.SIGWINCH` itself, i.e. line `board.py:2422` fails before `signal.signal` is
  even called). Windows has no analogous resize signal; the standard workaround is
  polling `os.get_terminal_size()` each frame (which the code already calls
  successfully elsewhere at `board.py:2281`, cross-platform-safe) instead of waiting
  for a signal.
- `signal.SIGHUP`: **also doesn't exist on Windows** — `signal.SIGHUP` is a plain
  `AttributeError`, at both `board.py:2414` and, separately, `collector.py:768`. Note
  `collector.py:770` wraps the *call* to `signal.signal` in `try/except ValueError`
  (for "not main thread"), which does **not** catch the `AttributeError` from merely
  referencing `signal.SIGHUP` in the tuple built one line above it — this line raises
  before the try block is ever entered. Same shape of bug in both files; not currently
  reachable on POSIX so it's never been hit, but it's a hard crash on Windows import
  of either `board.main()` or `collector._stop_on_signal()`.

### Recommended structure for a platform split
Don't try to make Windows console input produce raw termios-compatible bytes by hand
— instead keep the escape-sequence *parser* (`parse_sgr`) untouched and make the
Windows *source* of bytes ANSI-compatible too, via `ENABLE_VIRTUAL_TERMINAL_INPUT`
(`0x0200`) on the console input mode, set via `ctypes`
(`SetConsoleMode`/`GetConsoleMode` from `kernel32`, no third-party dep needed).
Windows Terminal and modern conhost (Win10 1809+, which is already the project's
stated minimum — matches herdr's own baseline per `_common.md`) will then deliver
arrow keys, and SGR mouse sequences if mouse mode is separately enabled through the
same console-mode bits, as the same ANSI byte sequences POSIX programs see. That
keeps `parse_sgr` as one shared, already-tested code path across all three platforms
— only the *plumbing that gets bytes into `buf`* forks by platform:

- POSIX: unchanged — `tty.setraw` + `select` + `os.read`.
- Windows: `SetConsoleMode` with `ENABLE_VIRTUAL_TERMINAL_INPUT` (equivalent of raw
  mode + ANSI decoding) in place of `tty.setraw`/`termios`; and in place of
  `select.select([fd],...,0.25)` + `os.read`, poll with `msvcrt.kbhit()` in the same
  0.25s loop cadence (call `kbhit()`, and if it's true, drain available bytes) — this
  preserves the existing "service two mailboxes every ~250ms, then check input"
  cadence without restructuring the loop into a thread-based design. `msvcrt.getwch()`
  reads one character at a time UTF-16-decoded, which is a mismatch with the
  UTF-8-oriented `buf += data.decode("utf-8", "replace")` — the Windows branch should
  read raw bytes instead (there isn't a clean stdlib byte-level non-blocking console
  read; likely needs `os.read(fd, 1024)` on the raw console handle *after* VT mode is
  enabled, since VT-mode-enabled consoles do support `ReadFile`-style byte streaming —
  this specific detail needs to be verified hands-on, I could not confirm it without a
  Windows box).
- `SIGWINCH` on Windows: replace with checking `os.get_terminal_size()` once per loop
  iteration and diffing against the last-seen size (cheap, and the loop already runs
  every ~250ms) instead of a signal-driven `dirty[0] = True`.
- `SIGHUP` on Windows: drop it from the signal tuple on that platform (there's no
  analogous "controlling terminal hung up" signal to catch) — guard with
  `hasattr(signal, "SIGHUP")` or an `if sys.platform != "win32"` filter, at both
  `board.py:2414` and `collector.py:768`.

**POSIX-regression risk of this plan: none** — the POSIX branch is untouched, and
`parse_sgr` gains no new caller behavior, only a second byte source feeding the same
`buf`.

**Test implications**: `parse_sgr()` itself is pure (str in, events out) and is
already the right unit to pin with input fixtures recorded from a real terminal — that
part is fully testable without Windows. The *raw-mode setup* and *read-loop plumbing*
are inherently untestable without a real console on each platform (this is exactly the
kind of thing CI's `ubuntu-latest`/`macos-latest`-only matrix, noted in prior
findings, already can't cover for POSIX raw mode either). A `windows-latest` CI leg
could at minimum prove `import switchboard.board` succeeds and
`os.get_terminal_size()` / the `SetConsoleMode` call round-trip without raising, which
is a meaningfully lower bar than proving the interactive loop works, but it's the
realistic ceiling for automated coverage here.

## 4. SQLite concurrency — `store.py`

**No file-level locking is layered on top of sqlite anywhere in store.py.** The entire
concurrency strategy is:

- `PRAGMA journal_mode=WAL` (`store.py:399`) — "many short-lived `sb` processes
  writing" per the inline comment.
- `PRAGMA busy_timeout=<_DB_TIMEOUT*1000>` (`store.py:400`) on every writer connection,
  and again on the read-only connection (`store.py:461`).
- One place relies on sqlite's own transaction semantics instead of a file lock, and
  says so explicitly: `broker.py:6039` `_claim_repair()` uses `BEGIN IMMEDIATE`
  (`broker.py:6051`) to make a read-then-insert atomic across processes, specifically
  *because* the comment says `fcntl` would be the wrong tool when "the contended thing
  here IS the store" — SQLite already serializes writers, so taking sqlite's own write
  lock is more precise than a side-channel file lock would be.
- Readonly connections use `mode=ro` URI (`store.py:458-459`), which is sqlite-level
  enforcement (`sqlite3.OperationalError: attempt to write a readonly database`), not
  filesystem permissions or a lock file.

### Windows assessment
This is the part of the audit with the best news. WAL mode is fully supported by
SQLite on Windows for local disk (not network shares — but that caveat is identical on
macOS/Linux too, it's not Windows-specific, and the store already lives under
`.git/agentflow`, i.e., local by construction for every supported workflow here).
`busy_timeout` and `BEGIN IMMEDIATE` are core SQLite behaviors with no OS-specific
code path — Python's `sqlite3` module links the same SQLite amalgamation on every
platform. I found:

- **No `os.unlink`/`os.remove` of the live db file anywhere in store.py** (grepped;
  only hits are docstring prose). `reset()`/`_reset()` (`store.py:891`) recreate the
  schema via `DROP`/`CREATE` SQL through the open connection, never by deleting the
  file — so the classic Windows "can't delete a file another process has open" problem
  never arises here.
- **`db_path`/store directory creation** uses `Path.mkdir(parents=True,
  exist_ok=True)` (`store.py:395`), which is platform-neutral.
- The one thing I could not verify without a Windows box: WAL mode creates `-wal` and
  `-shm` sidecar files next to the main db file, coordinated via shared memory mapping
  (`mmap`). SQLite's Windows VFS does support this, but it's worth an explicit
  smoke-test on the target platform (open two connections from two processes
  concurrently, confirm both see committed writes) before calling this settled — I'm
  reporting "no known blocker," not "verified working," for this one sub-point.

### Recommended fix
None needed for correctness — the existing WAL + busy_timeout + `BEGIN IMMEDIATE`
design is already Windows-portable by construction, because none of it reaches for a
POSIX-specific primitive. The only action item is the smoke test above, done once on
real Windows, not a code change.

## Spotted elsewhere (outside this scope, not chased)
- `subprocess.Popen(..., start_new_session=True)` at `panel.py:586`
  (`ensure_collector`) — `start_new_session` is documented as POSIX-only in the
  `subprocess` docs. I did not verify whether it's silently ignored or raises on
  Windows for the Python versions in scope (3.11/3.12) — needs a one-line check.
  Windows' actual equivalent for "detached, survives the launching pane closing" is
  `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS`.
  This sits right next to the panel lock code (`panel.py:435`) I was already reading,
  so flagging it here even though process-spawning is arguably a different concern
  than locking/terminal/DB.
- `signal.SIGHUP` also referenced at `collector.py:768` (same bug shape as
  `board.py:2414`, see §3) — collector.py is not otherwise in my assigned scope, but
  it shares the exact signal-handling pattern audited above.
- POSIX-only subprocesses (`lsof`, `ps -Ao`, `vm_stat`) already covered in prior
  findings and outside this scope; not re-audited here.

## Summary for the plan
1. **Locking**: small, low-risk internal shim (`switchboard/lockfile.py`), five call
   sites become one-line calls into it, zero POSIX behavior change, one Windows-side
   detail (byte-range-on-empty-file) worth a real test.
2. **Terminal input**: the largest single piece of work in this whole area. Keep
   `parse_sgr` as shared code; fork only the byte-source plumbing using
   `ENABLE_VIRTUAL_TERMINAL_INPUT` + `msvcrt.kbhit()` polling in place of
   `termios`/`tty`/`select`; drop `SIGWINCH`/`SIGHUP` on Windows with
   `hasattr`/platform guards, replacing `SIGWINCH` with a per-frame terminal-size
   diff. Needs hands-on Windows verification for the raw-byte-read step specifically.
3. **DB concurrency**: already Windows-safe by design (no fcntl-on-sqlite layering
   found); just needs a real-machine WAL smoke test, not a code change.
