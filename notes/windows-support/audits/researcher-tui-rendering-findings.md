# TUI rendering / ANSI / encoding / resize / stdin — Windows audit

Scope: `switchboard/board.py`, `switchboard/richboard.py`, `switchboard/output.py`.
Investigation only, no code changed. Confidence noted per item; nothing here was run
on a real Windows box (none available) — verified by reading CPython/rich source
behaviour where cited.

## 1. Hard import-time failures on native Windows (board.py doesn't even load)

- `board.py:55 import termios` — POSIX-only stdlib module, absent on Windows.
  Already flagged by the prior investigation.
- `board.py:58 import tty` — **not previously flagged, but equally fatal**: CPython's
  `tty` module does `import termios` unconditionally at its own module level, so on
  Windows this raises `ModuleNotFoundError` even before board.py's own `termios` line
  would (import order in the file makes it moot — either one alone kills the module).
- `board.py:57 import select` succeeds on Windows (module exists), but see §4 — the
  specific call used later does not work for what it's used for.
- Net effect: `switchboard/board.py` cannot be imported on native Windows at all,
  independent of the richboard/rich path. Nothing below matters until this is fixed,
  since `richboard.py` is loaded *by* `board.py` (`board._frame` picks the renderer)
  and never imported on its own.

**Fix shape:** isolate the raw-mode read primitive (`termios`/`tty`) behind a
platform seam — e.g. a `switchboard/rawinput.py` with a POSIX implementation (today's
code) and a Windows implementation using `msvcrt.getwch()`/`msvcrt.kbhit()` for
keypresses, since Windows has no termios equivalent and no raw-mode fd concept the
same way. This is genuinely two different input models, not a shim — coordinate with
whoever owns the raw-mode-read finding (locking-terminal researcher's remit per the
brief); this note covers only that the render loop's `while True` structure (select
timeout → drain → redraw) will need to poll `msvcrt.kbhit()` on a timer instead of
`select.select` on Windows, which is a design change to the loop, not just an import
swap.

## 2. `signal.SIGWINCH` doesn't exist on Windows

`board.py:2422: signal.signal(signal.SIGWINCH, on_resize)` — `SIGWINCH` is a Unix
signal name; the `signal` module simply does not define this attribute on Windows, so
referencing `signal.SIGWINCH` raises `AttributeError` at that line (this is a second,
independent failure point past the `termios`/`tty` import — even if those were ported,
this line still crashes unguarded).

Windows also has no exact equivalent notification for "the console was resized" via
a signal. Options, in order of fit for this codebase:
- **Poll `os.get_terminal_size()` every frame and diff it** — cheapest, and the loop
  already redraws on a `REFRESH` timer (`board.py:2526`) plus a 0.25s `select` timeout
  (`board.py:2473`), so a resize would show up within one tick (≤0.25s) for free if
  `dirty[0]` is set whenever the cached size changes. No new dependency, no Windows API.
  This is what I'd recommend — it also **improves** the POSIX path (SIGWINCH delivery
  can be missed/coalesced under load; polling can't miss a resize for longer than one
  tick).
- Console resize events *are* observable on Windows via `ReadConsoleInput` picking up
  `WINDOW_BUFFER_SIZE_EVENT` records on the input handle, but that requires trading the
  simple `os.read(fd, ...)` model for the Win32 console input API — more moving parts
  for the same result the poll gives you for free.
- Regression risk of the poll approach on macOS/Linux: none — it's strictly additive;
  `signal.signal(signal.SIGWINCH, ...)` can stay on POSIX (belt-and-suspenders, fires
  `dirty[0]=True` immediately instead of waiting for the next tick) guarded by
  `hasattr(signal, "SIGWINCH")`, with the poll as the actual source of truth on both.

## 3. ANSI/VT escape sequences — likely fine *if* board only ever runs inside a herdr
   ConPTY pane, unverified beyond that

`board.py` writes raw VT/ANSI directly, no library, no guard:
- `MOUSE_ON`/`MOUSE_OFF` (`board.py:71-72`): `\033[?1000h\033[?1006h` / off — SGR mouse
  reporting.
- `HIDE_CURSOR`/`SHOW_CURSOR` (`board.py:73-74`): `\033[?25l` / `\033[?25h`.
- `_c()` (`board.py:123-124`): raw SGR colour codes, e.g. `\033[31m...\033[0m`.
- `draw()` (`board.py:2331`): `\033[H\033[2J` — cursor-home + clear-screen, written
  every frame instead of a scroll-region diff.
- None of this goes through `colorama`, no `os.system('')` trick, no
  `SetConsoleMode(..., ENABLE_VIRTUAL_TERMINAL_PROCESSING)` call anywhere in the repo
  (`grep -rn "SetConsoleMode\|ENABLE_VIRTUAL_TERMINAL\|colorama\|PYTHONUTF8"
  switchboard/ bin/` — zero hits).

Why this may not matter: the brief's own framing is right that the board is reached
*only* through a herdr-opened pane (`board.py`'s own module docstring: "Three ways in,
all the same screen... `python3 -m switchboard.board` is the plumbing both go
through", and it refuses non-tty stdin at `board.py:2381`). herdr already carries
native Windows support via ConPTY (per the brief and the prior investigation's read of
the herdr binary). When a child process's stdout is attached to a Windows ConPTY, the
pseudoconsole — not the child — is what interprets VT sequences into console API calls,
and ConPTY's whole design assumes VT-speaking children; the host (herdr) configures the
pseudoconsole once, not each child. So switchboard's raw escape sequences plausibly
"just work" under a herdr-managed ConPTY pane the same way they do in a normal Unix
pty, **without switchboard itself calling `SetConsoleMode`**.

What I could not verify (no Windows box, and this is outside "the code" the brief asks
me to focus on): whether herdr's ConPTY host actually turns on
`ENABLE_VIRTUAL_TERMINAL_PROCESSING` for the pseudoconsole it creates, and whether
`python3 -m switchboard.board` run *directly* in a bare `cmd.exe` (bypassing herdr
entirely, which the module docstring calls "the plumbing" but doesn't forbid) would
land on a console with VT off. New console windows on Windows 10+ do **not** have
`ENABLE_VIRTUAL_TERMINAL_PROCESSING` on by default — an app has to opt in — so a direct
run outside herdr, in a legacy `cmd.exe` window that isn't itself Windows Terminal,
would very likely print literal `\033[31m...` garbage instead of colour. Windows
Terminal's own hosted panes do enable VT by default, so that direct-run path is
probably fine there.

**Recommendation:** don't hand-roll a VT-enable call in board.py — instead, at
process startup (wherever `sb board` / `python -m switchboard.board` bootstraps,
before board.main() touches stdout), call `SetConsoleMode` once, gated on
`sys.platform == "win32"` and only if not already inside a pane herdr manages
(`HERDR_PANE_ENV` is already read elsewhere per the prior findings — same signal could
gate this). This costs nothing on macOS/Linux (branch never taken) and only touches
Windows behaviour, so no regression risk to the two supported platforms. Cite the two
existing env markers `board.py:113-116` (`TAB_ENV`, `PANE_ENV`) as the established
pattern for "am I inside a herdr pane" detection to reuse here.

**Test implications:** the VT-enable call itself can't be exercised without a Windows
box (mocking `ctypes.windll` proves nothing about real console behaviour). What *can*
be pinned without Windows: that the call is gated correctly (only fires on
`win32`, only when the pane markers are absent) — a plain unit test monkeypatching
`sys.platform`.

## 4. `select.select` on `sys.stdin` — does not work on Windows for this fd type

`board.py:2473: r, _, _ = select.select([fd], [], [], 0.25)` where `fd =
sys.stdin.fileno()` (`board.py:2394`). On Windows, `select.select()` only accepts
socket objects/handles — passing a regular file or console-input fd raises
`OSError: An operation was attempted on something that is not a socket`. This is a
correctness break, not a degradation: the read loop cannot start at all on Windows as
written, independent of the `termios`/`tty` import failures in §1 (i.e. even a version
of this file that got past the imports would still die here).

Consistent with the brief's framing — this is the render loop's use of the primitive,
and the actual raw-mode keypress read belongs to the other researcher's remit, but the
loop *shape* (`select` with a timeout, to interleave "check for input" with "check for
worker-thread mailbox / refresh timer") has no direct Windows equivalent for stdin.
Recommended replacement discussed in §1: swap the whole "select with 0.25s timeout,
then read" pairing for `msvcrt.kbhit()` polled on the same 0.25s cadence (non-blocking
check, so the existing timer-driven redraw/mailbox-drain structure is unaffected) plus
`msvcrt.getwch()` to consume a byte once `kbhit()` says one is ready. This is a genuine
platform fork inside the loop body, best expressed as a small `_poll_input(fd) ->
bytes` seam so the surrounding `while True:` in `main()` doesn't itself need an
`if sys.platform == "win32"`.

**Test implications:** the loop's *handling* of decoded input (SGR parsing,
double-press timing, etc.) is already pure and tested via `parse_sgr`,
`double_press_run` — those need no changes and no Windows box. Only the raw
read-a-chunk-of-bytes primitive is platform-specific and untestable without Windows
(or a mocked `msvcrt`, which — as with §3 — proves the branch is gated right, not that
it behaves right on a real console).

## 5. Encoding — two real bugs, one Windows-only, one latent on any non-UTF-8 locale

- `board.py:2179` and `output.py:337`, both `path.open(errors="replace")` with **no
  `encoding=` argument** when reading Claude Code transcript JSONL files
  (`last_assistant_texts`, `_tail_records`). Python falls back to
  `locale.getpreferredencoding(False)` for the default text encoding. Claude Code
  writes these transcripts as UTF-8. On Windows, unless the process is running under
  Python's UTF-8 mode (`PYTHONUTF8=1`, or Python ≥3.15 where UTF-8 mode is default —
  brief says target is 3.11/3.12, so **not** default) or the "Beta: Use Unicode UTF-8"
  Windows system setting is on, the locale-preferred encoding is the legacy ANSI code
  page (commonly cp1252 on US/EU installs). Reading UTF-8 bytes as cp1252 doesn't
  necessarily throw (both are 8-bit supersets of ASCII), so `errors="replace"` mostly
  doesn't even trigger — instead **any non-ASCII character (box-drawing glyphs, emoji,
  accented text, CJK) in a transcript silently mojibakes** rather than erroring. This
  is worse than a crash because it's quiet.
  - **Also a latent bug today on Linux/macOS**, exactly as the brief expects for this
    class of finding: any POSIX box with `LC_ALL=C` / `LANG=` unset (containers, some
    CI images, minimal server installs) has `locale.getpreferredencoding(False)` return
    `'ascii'` or `'ANSI_X3.4-1968'`, not UTF-8 — same silent-mojibake failure mode,
    today, with no Windows involved. Nothing in `_prior-findings.md` mentions this;
    it's new.
  - **Fix:** add `encoding="utf-8"` to both `path.open(...)` calls. Trivial, zero
    regression risk — these files are always written by Claude Code as UTF-8, so
    naming it explicitly only removes a platform/locale-dependent guess, it doesn't
    change behaviour on any machine where the guess already happened to be UTF-8 (i.e.
    every properly configured macOS/Linux dev box today).
  - **Test:** easy and portable — write a small transcript fixture file with UTF-8
    bytes for a non-ASCII character, monkeypatch `locale.getpreferredencoding` (or run
    the test with `PYTHONUTF8=0` and a forced non-UTF-8 default via
    `io.open`'s locale kwarg override) to simulate a cp1252/ascii default locale, assert
    `last_assistant_texts`/`_tail_records` still returns the correct character. No
    Windows box needed — this is a pure encoding-selection bug, reproducible anywhere.

- `sys.stdout` write encoding for the glyphs themselves: `board.py` writes Unicode
  glyphs directly via `sys.stdout.write(...)` (`board.py:2333` in `draw()`, and the
  `_GLYPH_COLOR` set at `board.py:218`: `✗ ◐ ◌ ○ ●`) with no
  `sys.stdout.reconfigure(encoding="utf-8")` anywhere in the repo (grep confirmed, see
  §3). If Python's stdout encoding resolves to a non-UTF-8 codepage on Windows (same
  root cause as above — no UTF-8 mode forced), `sys.stdout.write` on a glyph either
  raises `UnicodeEncodeError` (with the default `errors="strict"` on stdout) or prints
  `?`/mojibake depending on the error handler in effect for that stream. This is a
  harder failure than the transcript-reading one because it's on the *write* path of
  the thing a human is staring at every frame, not a rare read of an old transcript.
  richboard.py has the same exposure once `available()` returns True (rich text
  ultimately reaches the same `sys.stdout.write` — see §6).
  - **Fix:** call `sys.stdout.reconfigure(encoding="utf-8")` (and stdin, for symmetry,
    though board.py reads raw bytes off the fd via `os.read`+`.decode("utf-8", ...)`
    itself at `board.py:2478` rather than through `sys.stdin`, so stdin's own encoding
    is less load-bearing here) once at `board.main()` startup, gated the same way as
    §3's VT-enable call — actually this one needs **no platform gate at all**:
    `reconfigure(encoding="utf-8")` is a no-op-equivalent correctness statement on
    macOS/Linux (already UTF-8 almost everywhere) and a real fix on Windows. Safest of
    all the fixes in this note.
  - **Test:** same shape as the transcript one — force a non-UTF-8 stdout encoding in
    a test harness (`io.TextIOWrapper` around a `BytesIO` with an explicit non-UTF-8
    encoding, monkeypatched in place of `sys.stdout`) and assert `draw()`'s write
    doesn't raise and round-trips the glyph correctly. Portable, no Windows needed.

## 6. `richboard.py` — `Console(..., legacy_windows=False, force_terminal=True)` throws
   away rich's own Windows compatibility shim

`richboard.py:1105-1106`:
```
console = Console(width=width, force_terminal=True, no_color=not _COLOR,
                  highlight=False, soft_wrap=False, legacy_windows=False)
```
`rich.console.Console` normally **auto-detects** whether it's running on a
pre-Windows-Terminal ("legacy") console and, if so, switches to a compatibility mode:
different behaviour for how ANSI is emitted (it can drive the Win32 console API via
its own internal colour handling rather than relying on raw VT bytes being
interpreted), and it's the mechanism the brief's prompt is asking about when it says
"note where switching to/relying on rich would help". Hardcoding `legacy_windows=False`
**disables exactly that auto-detection**, unconditionally telling rich "you are never
on a legacy Windows console" regardless of what's actually hosting the process. So the
one dependency in this codebase that already knows how to solve the Windows VT problem
has that solution turned off, on purpose (presumably because `force_terminal=True` is
needed to make Console render into `console.capture()`'s string buffer at all — see
`richboard.py:1111`, it's not writing to a real stdout, it's building a string board.py
then writes — so rich's own "am I on a real console" probing is moot for the render
call, but `legacy_windows` is a separate flag from `force_terminal` and isn't obviously
required to be `False` just because `force_terminal` is `True`).

Given richboard's whole render happens into a `console.capture()` string buffer
(`richboard.py:1111-1112`) rather than rich writing to stdout itself, `legacy_windows`
may not actually matter here — capture-based rendering to a string presumably always
produces the same VT-style ANSI text regardless of the legacy_windows flag, and
`board.draw()` is the thing that actually calls `sys.stdout.write()` on the result
(`board.py:2333`), which is the same raw write path as the plain renderer, i.e. subject
to §3's ConPTY/VT-enable analysis and not to any rich-specific Windows handling either
way. If that reading is right, `legacy_windows=False` is inert for this codepath and
this isn't a live bug — **I could not fully confirm this from reading the source
alone** (would need to check what `Console.capture()` does differently, if anything,
based on `legacy_windows` internally in the installed rich version) and flag it as
worth a quick check rather than a confirmed finding. Either way, the practical
takeaway is the same as §3: whatever ANSI/VT enabling switchboard needs on Windows has
to happen at the point something actually calls `sys.stdout.write` (`board.py:2333`),
which is common to both renderers — richboard's `rich` dependency is not, in its
current wiring, doing Windows VT/legacy-console work for switchboard, contrary to what
"rich handles a lot of this cross-platform" might suggest at a glance.

`richboard.py` itself has no platform-specific imports and no other terminal-control
code — everything else in that file is pure string/layout logic (box-drawing chosen
via `rich.box.ROUNDED`, a Unicode box style, drawn the same way regardless of
platform) — so it inherits board.py's problems (encoding, the VT question) rather than
adding new ones of its own, aside from the `legacy_windows=False` question above.

## 7. `NO_COLOR` / `isatty` handling

- `NO_COLOR` is read consistently in both renderers: `board.py:120` and
  `richboard.py:142`, both `os.environ.get("NO_COLOR") is None`. No Windows-specific
  concern — this is just an env var check, works identically everywhere. Note it does
  **not** check `isatty()` for the color decision (only board's `main()` checks
  `sys.stdin.isatty()`, and only to refuse a non-tty launch outright at
  `board.py:2381` — there's no "downgrade gracefully to no-colour when stdout isn't a
  tty" path, but that's consistent across platforms, not a Windows-specific gap, so
  it's out of scope for this audit beyond noting it exists.)
- `output.py` has no ANSI/color output at all — it renders transcript text as plain
  strings for a caller to display (`status.inspect` per its module docstring); nothing
  platform-specific found there beyond the `path.open()` encoding issue in §5, which
  is shared with `board.py`.

## Summary table

| # | file:line | Issue | Windows-fatal? | Also latent on POSIX? |
|---|---|---|---|---|
| 1 | board.py:55,58 | `import termios` / `import tty` | yes, import-time | no |
| 2 | board.py:2422 | `signal.SIGWINCH` undefined | yes, crashes | no |
| 3 | board.py:71-2331 | raw VT/ANSI, no `SetConsoleMode`/colorama | maybe not, if always under herdr ConPTY — unverified outside herdr | no |
| 4 | board.py:2473 | `select.select` on stdin fd | yes, `OSError` | no |
| 5a | board.py:2179, output.py:337 | `path.open()` missing `encoding="utf-8"` | silent mojibake | **yes** — any POSIX box with non-UTF-8 locale |
| 5b | board.py:2333 (write side) | no `sys.stdout.reconfigure(encoding="utf-8")` | `UnicodeEncodeError` or mojibake on glyph write | same as 5a |
| 6 | richboard.py:1105-6 | `legacy_windows=False` forced | unclear/likely inert (capture-based) | no |

## Spotted elsewhere (outside this concern, not chased)

- `board.py`'s `_open`/report-opening path (`board.py:2155` area) shells out via the
  `_ACTIONS` table (not read in detail — outside this file's rendering concern) to open
  reports; if that uses POSIX-specific opening commands it'd be the sweep/subprocess
  researcher's concern, not rendering.
- The prior-findings note's `fcntl`/`lsof`/`ps` inventory (broker.py, plugins.py,
  panel.py, sweep.py, live.py, stats.py) is confirmed still current by file:line
  spot-check but is someone else's concern per the brief's split.
