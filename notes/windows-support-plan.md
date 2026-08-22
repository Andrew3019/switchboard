# Windows support for switchboard — comprehensive plan

Investigation only, 2026-08-22. No production code changed. Goal: native Windows support for
all of switchboard (`sb`/broker/plugins/panel/sweep/board/hooks/worktrees) with **zero
regression** to macOS/Linux — both keep working correctly, Windows is gained on top.

Built from six independent concern-scoped audits (full detail, every `file:line`, in
`.switchboard/notes/researcher-*-findings.md`). This document is the synthesis and the plan.

---

## 0. Headline corrections to the prior investigation

The prior migration note (`notes/pc-migration-findings.md`, branch `worker-pc-migration-check`)
was a good starting map but got three things wrong, verified here:

1. **The "Linux `lsof` gives 3-line groups" bug does NOT exist.** Tested directly against real
   GNU `lsof` (Docker: Ubuntu 22.04 + Debian 11, the `lsof-org` fork every current distro
   ships): `lsof -a -d cwd -F pcn` emits the same 4-line `p`/`c`/`fcwd`/`n` groups as BSD/macOS.
   `live._parse` already works on Linux. **The `skipUnless(darwin)` at `tests/test_live.py:70-72`
   and the CI comment are based on an unverified assumption and should be removed** (replace with
   a static-fixture test). Consequence: `sb workspace close` on WSL is *not* broken as claimed.
2. **`os.environ['HOME']` is never used.** Grepped the whole package — every home lookup goes
   through `Path.home()`/`.expanduser()`, already Windows-correct. The prior note described a
   generic risk, not a real citation.
3. The prior note missed the real hard blockers below (SIGHUP/SIGWINCH crashes, the
   `_ready_pane` bash string, `select.select` on stdin, the `os.access(X_OK)` lie).

A real *different* Linux quirk was found: unprivileged Linux `lsof` lists foreign-user pids with
a junk `n/proc/<pid>/cwd (readlink: Permission denied)` name instead of omitting them. Harmless
today (never matches `is_under`) but contradicts `live.py`'s documented scope invariant — fix
the docstring, not the code.

---

## 1. Decisions that are not mine to make silently

These change macOS/Linux behaviour or reverse a documented decision. Each needs an explicit
sign-off before implementation — they are the real "design questions" in this port.

### D1. Process scanning: adopt `psutil`, or hand-roll per-OS? — **DECIDED (Andrew, 2026-08-22): adopt psutil**
`live.py` (`lsof`), `stats.py` (`ps`/`vm_stat`), and `broker._parents` (`ps`) are three
hand-parsed POSIX subprocesses. Windows has no `lsof` equivalent for "which process has this
cwd". `psutil` (BSD-3, prebuilt cp311/cp312 wheels for win/mac/linux, no compiler) replaces all
three with one tested library and gives Windows a real per-process cwd via the PEB.
- **Cost 1:** a *required* third-party dep. `stats.py:497-499` explicitly rejected `psutil`
  before ("a dependency the collector's interpreter is not promised"). Adopting it reverses that
  on the record, not by side effect.
- **Cost 2:** it changes close-gate epistemics *on macOS/Linux too*. Today a missing binary /
  bad exit ⇒ `scan()` returns `None` ⇒ close-gate fail-safe refuses (`broker.py:2305`). `psutil`
  essentially never fails wholesale, so those false refusals get rarer — desirable, but a
  behaviour change on the existing platforms, so it must be tested and called out, not shipped
  quietly.
- Alternatives: hand-rolled `ctypes` Win32 (`CreateToolhelp32Snapshot` + PEB read — the cwd part
  is the hard, permission-sensitive bit psutil already solves); or `wmic`/PowerShell shell-outs
  (rejected: `wmic` removed in Win11 24H2, PowerShell startup ~200-500ms makes Windows slower
  than the platform it matches).
- **Recommendation:** adopt `psutil` as one shared `procscan` abstraction. It also collapses the
  parsing-bug risk class entirely. If the "no new required dep" posture is firm, the fallback is
  ctypes-Win32 for Windows only, keeping the POSIX subprocesses untouched (larger Windows-only
  maintenance surface, no macOS/Linux behaviour change).

### D2. Packaging: `pyproject.toml` console-scripts vs committed per-checkout `.cmd` shims — **DECIDED (Andrew, 2026-08-22): do both**
`bin/sb`, `bin/sb-stop-hook`, `bin/sb-activity-hook` are extensionless `#!/usr/bin/env python3`
scripts. Windows cannot launch them (no shebang, no `PATHEXT` match) — `sb` won't run and hooks
never fire.
- A `pyproject.toml` `[project.scripts]` (`sb = switchboard.cli:main`, plus two hook entries)
  makes `pip install -e .` generate a real `sb.exe`/POSIX shim from one source on all three OSes.
  Cleanest, and removes the manual `~/.local/bin/sb` symlink and "whatever python3 is on PATH"
  ambiguity everywhere.
- **Tension:** the per-worktree PATH-pin (`broker.py:3295-3360`) exists precisely so each
  worktree runs *its own* checkout's code, not one global install — the bug called out at
  `broker.py:384-385` ("acceptance-tested against code that was never running"). A single global
  console-script reintroduces exactly that. So the Windows bin dir must contain something
  `PATHEXT`-resolvable *per checkout*.
- **Recommendation:** ship committed `bin/sb.cmd`, `bin/sb-stop-hook.cmd`, `bin/sb-activity-hook.cmd`
  shims (`@py -3 "%~dp0sb" %*` style) alongside the untouched POSIX scripts — preserves the
  per-worktree PATH-pin with zero POSIX change — AND add a `pyproject.toml` for the clean
  install path. Also fold the two duplicated hook scripts into one `switchboard/hooks_entry.py`
  (`--stop`/`--activity`), a net simplification independent of Windows.

### D3. State directory convention — **DECIDED (Andrew, 2026-08-22): use the SAME path everywhere, no change**
`~/.local/state/switchboard` (`defaults/settings.toml:66`) *works functionally* on Windows —
`~` resolves to the user profile, so files land under `C:\Users\<name>\.local\state\switchboard`.
The only argument for changing it was Windows-convention/tooling recognition; Andrew has
explicitly waved that off ("forget the backup and cleanup tools"). So **no code change at all** —
the same literal path on all three OSes. Zero work, zero regression.

### D4. Symlink strategy on Windows — **DECIDED (Andrew, 2026-08-22): Option A — Developer Mode + real symlinks, keep fallback in code**
`broker.py:1116` `dst.symlink_to(src)` needs Developer Mode/admin on Windows and, even when
privileged, creates the wrong link *type* for the `.switchboard` directory. On failure it
silently logs `link_failed` and every worktree loses `.switchboard` (briefs, notes, roles,
presets, models — all invisible) and `CLAUDE.md` (no repo context).
- **Andrew's machine (primary target):** enable **Developer Mode** (a one-time Windows Settings
  toggle) so real symlinks work exactly as on macOS — one true shared copy, no drift. Code fix:
  pass `target_is_directory=src.is_dir()` (free/correct on POSIX where it's ignored, correct on
  Windows for a directory target).
- **Robustness fallback (still built, for machines without Developer Mode):** on symlink failure,
  use a **directory junction** (`_winapi.CreateJunction`, no privilege) for `.switchboard` and a
  **copy** for `CLAUDE.md` (junctions can't target files). The copy path loses the "exactly one
  true file" design (`broker.py:69`) — a real regression *in spirit*, but it only applies on a
  machine that can't enable Developer Mode, not Andrew's.
- Either way, update the two `is_symlink()` detection sites (`broker.py:1113`, `:1856`, M5) in
  lockstep so a junction/copy isn't misread as "not ours."

### D5. How does a *plugin* get the lock primitive? — **OPEN (new, raised by adversarial review round 1)**
`defaults/plugins/plans/__init__.py:379` imports `fcntl` at module scope and flocks the plan-id
mint at `:2869` (B7). So `lockfile.py` (B1) has to be reachable from plugin code, and today it is
not: every shipped plugin imports exactly `switchboard.plugins` and nothing else
(`report-bug:59-60`, `todo:49`, `suggestions:60`, `plans:390`), a contract `sb doctor` polices and
`report-bug/__init__.py:284-287` states in prose. Two ways out, and this is not a preference:
- **Re-export `lock`/`unlock` through `switchboard.plugins`** — the contract stays one module wide,
  plugins get the primitive, one implementation. *Recommended.*
- **Widen the contract** to allow `switchboard.lockfile` — more honest as a layering statement,
  but it makes "what a plugin may import" a list rather than a single name, and `sb doctor` and
  the prose at `report-bug:284-287` both have to move with it.
- (Rejected third option: let each plugin platform-branch its own locking inline. Duplicates the
  msvcrt/fcntl branch per plugin — the exact thing `lockfile.py` exists to prevent.)

---

## 2. Complete inventory of platform-specific code paths

Severity: **BLOCKER** = nothing works (import/spawn fails); **BREAK** = runs but wrong/fails;
**MINOR** = degraded/cosmetic; **VERIFY** = no code change, needs a real-Windows smoke test.

**Scope.** The six source audits were all pointed at `switchboard/`. `defaults/` — ~10k lines of
shipped plugin code — was never in any of their scopes, so the first version of this inventory
inherited that hole exactly. Adversarial review round 1 swept `defaults/` and `bin/` with the same
POSIX-API list; what it found is folded in below (B7, F6, F11, F12, F13, and the widened F9/V2).
Entries now name a **class with a grep behind it**, not the one line an audit happened to touch —
the earlier F9 and V2 read as exhaustive site lists and were not.

### Hard blockers — switchboard does not start / no agent spawns

| # | file:line | What | Fix |
|---|---|---|---|
| B1 | `broker.py:33`, `plugins.py:62`, `panel.py:69`, `sweep.py:44` | `import fcntl` (module-level) — 4 sites in `switchboard/`; see B7 for the 5th | route 6 lock sites through new `switchboard/lockfile.py` (D-below) |
| B2 | `board.py:55,58` | `import termios` / `import tty` (also kills `richboard` via `from . import board`) | platform seam `switchboard/rawinput.py` |
| B3 | `collector.py:768`, `board.py:2414` | `signal.SIGHUP` referenced in a tuple — `AttributeError`, **not** caught by the `except ValueError`; crashes collector at startup / board on entry | guard with `hasattr(signal, "SIGHUP")` / platform filter |
| B4 | `board.py:2422` | `signal.signal(signal.SIGWINCH, …)` — `SIGWINCH` undefined on Windows | drop on Windows; replace with per-frame `os.get_terminal_size()` diff |
| B5 | `broker.py:3341-3356` (`_ready_pane`, called every spawn+restore at `:3693`,`:5375`) | types `export PATH=…:"$PATH"; echo "sb=$(command -v sb)"` — bash-only — into the pane; `wait_output` times out ⇒ `SbUnpinned` on **every** Windows agent | branch command by pane shell family (cmd/pwsh/posix). **Also branch the marker** at `broker.py:3348` — `marker = f"sb={bin_dir}/sb"` hardcodes both `/` and the extensionless name, and it is what `wait_output` matches. A branch that fixes the command and not the marker still times out into `SbUnpinned` |
| B6 | `bin/sb` + `hooks.py:113/126/143` + `bin/sb-stop-hook`/`sb-activity-hook` | extensionless shebang scripts; `sb` unlaunchable, Stop/activity hooks never fire (silently, "fails open") | D2 packaging + `.cmd` shims |
| B7 | `defaults/plugins/plans/__init__.py:379` (`import fcntl`), `:2869` (`flock` on the `_minting` id lock) | **The plans plugin dies silently on Windows.** `plugins._import` (`plugins.py:397`) catches `BaseException` and `load()` turns it into `status="broken"` — so `sb` does not crash, the plans plugin just answers "broken: No module named 'fcntl'" to every `sb plugin plans …`. That is the merge-gate machinery gone, reported only as a plugin health line. | route through `lockfile.py` — which needs **D5** first (a plugin cannot import `switchboard.lockfile` under today's contract) |

### Functional breaks — runs, produces wrong result or fails at use

| # | file:line | What | Fix |
|---|---|---|---|
| F1 | `live.py:61,89` | `lsof -a -d cwd -F pcn` — degrades safely to `None` on Windows (⇒ close always refuses) | D1 `procscan`/psutil |
| F2 | `stats.py:438` (`ps -Ao`), `stats.py:515` (`vm_stat`), `broker.py:2464` (`ps -Ao` in `_parents`) | POSIX-only process/memory subprocesses | D1; add `_available_windows()` to the `sys.platform` dispatch at `stats.py:501` |
| F3 | `board.py:2473` | `select.select([stdin_fd],…,0.25)` — Windows `select` rejects non-socket fds (`OSError`) | Windows branch: `msvcrt.kbhit()` polled on the same 0.25s cadence |
| F4 | `board.py:2395,2452,2406` | `termios.tcgetattr`/`tty.setraw`/`tcsetattr` raw-mode | Windows: `SetConsoleMode` + `ENABLE_VIRTUAL_TERMINAL_INPUT` via `ctypes`; keep `parse_sgr` shared |
| F5 | `broker.py:1116` | `symlink_to` no `target_is_directory`, no capability fallback | D4 |
| F6 | **4 sites:** `board.py:2217`, `collector.py:475`, `broker.py:415`, `defaults/plugins/plans/__init__.py:3573` (`_sb()`) | `os.access(path, os.X_OK)` — always True on Windows (no exec bit), then `subprocess.run` fails deep with `WinError 193` | check for the `.cmd`/`.exe` shim's existence; invoke that path. Verified in the fix's favour: a `.cmd` **full path** does execute through `subprocess.run` (CreateProcess falls back to `cmd.exe` for `.bat`/`.cmd`), and `shutil.which` does consult `PATHEXT`. The break is the bare name, not the extension — see F6b |
| F6b | `defaults/plugins/report-bug/__init__.py:269` | `subprocess.run(["sb", "inspect", …])` — a **bare literal**, no `shutil.which`, no own-checkout resolution. Windows `CreateProcess` appends only `.exe` when searching PATH and does **not** consult `PATHEXT`, so under D2's committed-`.cmd`-shim path this never resolves and bug filing silently loses its pane-tail attachment | resolve through the same `_sb()`-shaped helper the other three sites use (arguably a POSIX cleanup too — it is the only unresolved `sb` in the repo) |
| F7 | `hooks.py:113/126/143`, `broker.py:3343` | `shlex.quote` — POSIX quoting; breaks on Windows paths with spaces | branch on `os.name`; use `subprocess.list2cmdline`/`"..."` for Windows, keep `shlex.quote` for POSIX |
| F7b | `hooks.py:157` (`p.read_text()`), `:160` (`tmp.write_text(body)`) | the **same two lines** write Claude Code's `settings.json` with no `encoding=`. Claude Code reads that file as UTF-8; this writes it in the ANSI code page. A checkout path with any non-ASCII character produces a settings file Claude Code mis-parses or reads a wrong path out of — and hooks never fire, silently | `encoding="utf-8"` on both. Part of the F9 class, called out separately because the consequence is "hooks are dead", not "text looks wrong" |
| F8 | `board.py:2269` | `prompt_pane(…, "exec {python} -m switchboard.board")` — `exec` is a POSIX builtin | drop `exec` on Windows panes (not load-bearing) |
| F9 | **A package-wide class, not two lines.** No text read in this codebase passes `encoding=`. On Windows `Path.read_text()`/`open()` fall back to `locale.getpreferredencoding(False)` — the ANSI code page, cp1252 on a default install, not UTF-8 (3.11/3.12; UTF-8 mode is only the default from 3.15). The grep is `grep -rn -e 'read_text(' -e '.open(' -e 'write_text(' switchboard/ defaults/`, minus the lines that already pass `encoding=`. Sites: `board.py:2179`, `output.py:337`, `defaults/plugins/plans/__init__.py:3848` (the three `errors="replace"` opens); `config.py:163` (`read_toml`), `:191` (`read_text`), `:425`, `:453`; `models.py:213`; `presets.py:167`, `:220`; `plugins.py:336`; `store.py:108`/`:118`; `sweep.py:313`/`:319`; `panel.py:136`/`:145`; `broker.py:1134`, `:4090`; `collector.py:568`; `defaults/plugins/plans/__init__.py:3350`; and F7b | **Silent corruption of the artefact switchboard exists to produce.** Measured, not assumed: `defaults/protocol.md` (192 non-ASCII bytes) and `defaults/settings.toml` (293) both decode *successfully* as cp1252 into mojibake (`'sessions â€” in this repo'`). `config.py:191` is what reads `protocol.md`, every role `.md` and `agent.md` — i.e. **every agent's spawn prompt is mojibake on a default Windows install**. `read_toml` corrupts any setting *value* containing `—`/`’`. Contrast `herdr.write_prompt_file` (`herdr.py:145,147`), which already passes `encoding="utf-8"` — which is why this is a gap and not the whole codebase | add `encoding="utf-8"` at every site. Zero-risk on POSIX (it is what a UTF-8 locale already does) and it fixes the same **latent POSIX bug** under `LC_ALL=C` / minimal containers |
| F10 | `board.py:2333` write path | no `sys.stdout.reconfigure(encoding="utf-8")` ⇒ glyphs (`✗◐◌○●`) raise `UnicodeEncodeError`/mojibake on a non-UTF-8 codepage | `sys.stdout.reconfigure(encoding="utf-8")` at board startup — no platform gate needed |
| F11 | `bin/sb-stop-hook:28`, `bin/sb-activity-hook:27` — `hooks.run(sys.stdin.read())` | the **read** side of F10. `sys.stdin` decodes a pipe with the ANSI code page and `errors='strict'`. `0x81 0x8D 0x8F 0x90 0x9D` are undefined in cp1252, so a payload containing e.g. `●` (UTF-8 `E2 97 8F`) raises `UnicodeDecodeError` before `json.loads` runs. Both scripts catch it and return 0 — hooks fail open by design (B6) — so the Stop gate silently never fires for that turn and nothing is logged | `sys.stdin.reconfigure(encoding="utf-8")` in the hook entry point; lands naturally in D2's `hooks_entry.py` alongside F10 |
| F12 | 26 `subprocess.run(..., text=True)` sites across `switchboard/` and `defaults/` (e.g. `defaults/plugins/report-bug/__init__.py:269`, `plans/__init__.py:3556`, `plans/analysis/evidence.py:110`) | `text=True` with no `encoding=` decodes the child's stdout with the ANSI code page too. Reading `sb … --json` output containing an em-dash gives mojibake through `json.loads`, or a `UnicodeDecodeError` on the undefined cp1252 bytes | pass `encoding="utf-8"` alongside `text=True`. Same class as F9, same zero-risk POSIX fix. *(Found while verifying F9; not in the round-1 findings.)* |
| F13 | `panel.py:583` `start_new_session=True` (the collector spawn, `panel.py:576-586`) | **was V6, and V6's verdict was wrong.** V6 said CPython maps this to `CREATE_NEW_PROCESS_GROUP` on Windows. It does not: CPython 3.11.5's Windows `_execute_child` takes it as `unused_start_new_session` (`subprocess.py:1445`) and never reads it; the docstring at `:785` says "POSIX only". It is **silently discarded** — no `creationflags` are set. This is the repo's single elected collector, and `start_new_session` is what detaches it from whichever renderer won the election. On Windows it stays in that renderer's console and process group: a Ctrl-C in that pane, or closing that console window, takes the fleet's collector down and every panel goes stale | Windows branch adding `creationflags=DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP`; keep `start_new_session=True` unchanged on POSIX |

### Minor / cosmetic

| # | file:line | What | Fix |
|---|---|---|---|
| M1 | `defaults/settings.toml:66` (`plugins.py:608`) | `~/.local/state/switchboard` wrong convention | **none** — D3 decided: keep same path on all OSes |
| M2 | `board.py:1684` `_PATHLIKE` | regex rejects drive-letter/backslash paths ⇒ click-through feature silently no-ops | widen regex / `PureWindowsPath(...).as_posix()` on nt |
| M3 | `herdr.py:239`, `store.py:962` | `~/.local/bin/herdr` fallback (after `shutil.which`) | platform-conditional fallback dir; low priority, `which` almost always wins |
| M4 | `richboard.py:1105` | `legacy_windows=False` forced | likely inert (renders to a `capture()` string buffer) — verify, don't assume |
| M5 | `broker.py:1113`, `:1856` | `is_symlink()` as sole "is this ours" check | must update in lockstep with D4 (junction/copy read as `unknown`) |
| M6 | `live.py:26-37` docstring; `is_under` case-fold on NTFS — the comparison is **`live.py:136`** (`return p.parts[:len(r.parts)] == r.parts`); the earlier citation of `live.py:82` pointed inside `scan()`'s docstring | scope invariant is macOS-specific; `PurePath.__eq__` *is* case-insensitive on Windows but a tuple-of-`.parts` comparison is not — which is exactly the trap | doc fix + case-fold comparison on Windows |

### Verify-only (no code change; needs a real Windows box / CI runner)

- **V1** SQLite WAL + `busy_timeout` + `BEGIN IMMEDIATE` (`store.py:399-400`, `broker.py:6051`) —
  already Windows-portable by design (no fcntl-on-sqlite layering; `reset()` never unlinks the
  db file). Smoke-test two concurrent connections see committed writes; confirm `-wal`/`-shm`
  sidecars work.
- **V2** The tmp + `os.replace`-with-unlocked-readers shape has **four writers**, not one:
  `panel.py:250-259`/`:315`, `defaults/plugins/plans/__init__.py:3336` and `:3211`, and
  `defaults/plugins/todo/__init__.py:221`. The plans plugin is the *worst* case, not panel.py: it
  documents at `:396`/`:367-368` that it takes **no coarse lock**, so its readers are explicitly
  unsynchronised. Spike the "40 readers + 1 writer" case against the plans store, not just the
  snapshot.
  The open question is whether `os.replace` raises `PermissionError` under a concurrent reader.
  The earlier claim that CPython's reader "relies on `FILE_SHARE_DELETE`" carried no citation and
  could not be confirmed: CPython's Windows `open()` goes through the CRT `_wopen`/`_SH_DENYNO`,
  which grants read+write sharing — whether it grants *delete* sharing is the whole question.
  **Unverified in both directions**; "very likely fine" was not evidence either.
- **V3** ConPTY actually enables `ENABLE_VIRTUAL_TERMINAL_PROCESSING` for herdr panes (raw ANSI
  in `board.py` "just works" under herdr; a *direct* run in legacy `cmd.exe` outside herdr would
  print escape garbage — recommend `SetConsoleMode` once at board startup, gated on `win32` and
  absence of the herdr pane env markers `board.py:113-116`).
- **V4** Claude Code's hook runner shell/quoting on native Windows (cmd.exe vs PowerShell vs
  direct exec) — determines the exact hook-command quoting. Confirm via `claude-code-guide` or a
  real install; the `shlex`-is-wrong finding holds regardless.
- **V5** `msvcrt` raw byte read after VT-input mode (the one input-plumbing detail nobody could
  confirm without a console).

### The shared primitives to build

- **`switchboard/lockfile.py`** — `lock(fd, *, blocking)` / `unlock(fd)`. POSIX branch = today's
  `fcntl.flock` extracted verbatim (6 sites: `plugins.py:687`, `sweep.py:308`, `panel.py:435/453/474`,
  `broker.py:2863`, and `defaults/plugins/plans/__init__.py:2869` — the last reachable only once
  **D5** says how, see B7). Windows branch = `msvcrt.locking` at offset 0 after `os.lseek(0)` (must lock
  the *same* byte range at all sites to contend). ~40 lines; recommended over a `portalocker`
  dep. All 6 locks are whole-file, advisory, exclusive, cross-process, on a *separate* 0-byte
  `.lock` file (never the data file) — so Windows *mandatory* byte-range locking never collides
  with the separate `tmp + os.replace` data rewrite. One rule to preserve: never read a `.lock`
  file's contents from a second process without holding the lock (works by accident on POSIX,
  `PermissionError` on Windows).
- **`switchboard/rawinput.py`** — the raw-mode keypress seam. POSIX = `termios`/`tty`/`select`
  unchanged. Windows = `ENABLE_VIRTUAL_TERMINAL_INPUT` + `msvcrt.kbhit()` polling. **Keep
  `parse_sgr` (`board.py:139`) as the single shared parser** — only the byte *source* forks.
- **`switchboard/procscan.py`** (if D1 = psutil) — one enumeration serving `live.scan`,
  `stats` memory/process sampling, and `broker._parents`.
- **`switchboard/hooks_entry.py`** — one module replacing the two duplicated hook scripts.

---

## 3. Phased implementation plan

Every phase is written as "add a Windows branch," never "rewrite the POSIX one." Ordering is by
dependency: nothing downstream can be tested on Windows until the import-time blockers clear.

**Phase 0 — decisions.** D1–D4 are settled (§1). **D5 (how a plugin reaches `lockfile`) is open and
gates B7** — settle it before Phase 1 touches the lock sites, because it decides whether `lockfile`
is re-exported through `switchboard.plugins` or the plugin import contract widens.

**Phase 1 — make it import on Windows (unblocks all testing).**
- `lockfile.py` shim; convert the 6 fcntl sites — 5 in `switchboard/` (B1) and the plans plugin's
  (B7), the latter via whatever D5 decides. Pure extraction on POSIX.
- `rawinput.py` seam so `board.py`/`richboard.py` import without `termios`/`tty` (B2).
- Guard `SIGHUP` (B3) and `SIGWINCH` (B4) with `hasattr`/platform filters in `collector.py` and
  `board.py`.
- Add the whole F9 encoding class now, plus F7b, F10, F11, F12 (cheap, mechanical, and each also
  fixes a latent POSIX bug under a non-UTF-8 locale).
- Exit criteria: `import switchboard.*` succeeds on `windows-latest`; pytest *collects*; **and
  `sb plugin list` reports every shipped plugin `ok`.** That third criterion is not decoration:
  plugins load by path through `spec_from_file_location`, not as `switchboard.*`, and
  `plugins.load` swallows the failure into `status="broken"` — so the first two criteria pass
  with the plans plugin (and the merge gate) silently dead. That is exactly how B7 was missed.

**Phase 2 — make `sb` runnable and hooks fire (B6, D2).**
- `pyproject.toml` console-scripts + `hooks_entry.py` + committed `.cmd` shims.
- Fix `hooks.py` quoting (F7) and `_entry_point` to return the `.cmd`/entry path on nt.
- Replace the 4 `os.access(X_OK)` checks (F6) with shim-existence checks, and resolve
  `report-bug`'s bare `"sb"` literal (F6b).
- Exit criteria: `sb --help` runs on Windows; a registered Stop hook actually fires (V4).

**Phase 3 — make agent spawn work (B5, F8).**
- Branch `_ready_pane` (B5) and `board.open_beside` (F8) by pane shell family. Needs a
  herdr-reported "what shell does this pane run" fact — confirm herdr's API exposes it; do not
  infer from the Python process's platform (pane shell is a herdr/OS property).
- Exit criteria: an agent spawns and pins into a Windows pane.

**Phase 3b — collector detachment (F13).** Windows `creationflags` on the `panel.py:583` spawn.
Small, but it is the difference between one elected collector and a collector that dies with a
console window. Exit criterion: closing the electing renderer's console leaves the collector up.

**Phase 4 — process/liveness backend (D1, F1/F2).**
- `procscan.py` (psutil or ctypes); repoint `live.scan`, `stats`, `broker._parents`.
- Add `_available_windows()` to the `stats` memory dispatch.
- Fix the `live.py` docstring + `is_under` NTFS case-fold at **`live.py:136`** (M6); remove the bogus
  `tests/test_live.py` Linux skip and add a static-fixture parse test.
- Exit criteria: `sb workspace close` gate answers correctly on Windows; CPU/mem stats populate.

**Phase 5 — worktree filesystem (D4, F5, M5).**
- `symlink_to` → `target_is_directory` + junction/copy fallback; update the two `is_symlink`
  detection sites in lockstep.
- Exit criteria: a fresh worktree on an unprivileged Windows box has working `.switchboard` +
  `CLAUDE.md`.

**Phase 6 — interactive board input/render (F3, F4, V3).**
- Wire `rawinput.py`'s Windows byte source into the read loop; `SetConsoleMode` VT-enable at
  startup (gated); SIGWINCH→poll.
- Exit criteria: the board draws and takes keys inside a herdr Windows pane. (Least
  CI-verifiable — largely hands-on.)

**Phase 7 — polish + verify.** M1–M4, M6; run the V1–V5 smoke tests on a real box; update the
README "Status" disclaimer.

Phases 1–5 are largely CI-verifiable via platform-parameterized unit tests. Phase 6 and the V-items
need hands-on Windows.

---

## 4. Testing & CI strategy

- **Add `windows-latest` to `.github/workflows/tests.yml`** (matrix is ubuntu+macos today,
  `fail-fast: false` already set, so it's additive — no risk to existing legs). First failures,
  in order: (1) collection-time import errors (B1–B4) blank the suite until fixed; (2) `lsof`/
  `ps`/`vm_stat` tests need Windows skips or the psutil backend; (3) mocked-`Herdr` tests should
  pass once imports clear; (4) any `bin/sb`-execution tests fail until Phase 2.
- **Register `windows`/`posix` pytest markers** (in the new `pyproject.toml`) instead of ad-hoc
  `skipif(sys.platform…)` scattered around, so "what runs only on Windows" is one grep. Mirrors
  the existing `tests/test_live.py` skip precedent.
- **High-value tests that need no Windows box** (write these regardless of when the port lands):
  - Command-string builders parameterized on shell family — assert the Windows branch never emits
    a bare single-quoted path, and the POSIX branch is **byte-identical to today** (pins the
    no-regression guarantee). Covers B5, F7, hooks.
  - `_entry_point()` returns a `.cmd` path under monkeypatched `os.name == "nt"`.
  - `link_config` falls back to copy when `os.symlink` raises `OSError(1314)` (D4).
  - `live._parse` accepts the captured GNU-lsof 4-line fixture (kills the bogus skip).
  - Encoding: transcript read + glyph write round-trip under a forced non-UTF-8 locale (F9/F10) —
    reproducible on any OS. Extend it to the **spawn-prompt path** (`config.read_text` →
    `defaults/protocol.md`), which is the site where the corruption actually costs something.
  - `sb plugin list` reports every shipped plugin `ok` — a regression test for B7's failure mode,
    where a plugin import error is swallowed into a health line nobody reads. Runs on every OS.
  - `SIGHUP`/`SIGWINCH` guards don't raise with the attribute mocked absent (B3/B4).
- **`defaults/` is in scope for all of the above.** The first cut of §2 and §4 covered
  `switchboard/` only; the plugins carry their own `fcntl`, their own `os.access(X_OK)`, their own
  unresolved `"sb"`, their own encoding sites and their own `os.replace` concurrency.
- **Cannot be pinned in CI** (integration on real Windows only, per the house testing rules —
  don't grow a fake to fake it): the interactive board loop, ConPTY VT behaviour, Claude Code's
  hook runner, psutil's Windows cwd/`AccessDenied` shape, the WAL concurrency smoke test. CI has
  no herdr and no tmux even on the runner (already true for POSIX), so pane-level behaviour is
  never CI-provable.

---

## 5. What is unproven (stated, not silent)

Every Windows-specific behavioural claim here is from documented CPython/psutil/SQLite platform
behaviour, **not** run on a real Windows machine (none available to the researchers). Specifically
unproven: msvcrt byte-range lock on an empty file; `ENABLE_VIRTUAL_TERMINAL_INPUT` delivering SGR
sequences; the msvcrt raw-byte read (V5); psutil's Windows cwd/`AccessDenied` (D1); ConPTY VT
(V3); WAL sidecars (V1); `os.replace` mid-read share modes and whether CPython's Windows `open()`
grants delete-sharing (V2 — unverified in *both* directions, not "very likely fine"); Claude Code's
hook-runner shell (V4); `CreateProcess` ignoring `PATHEXT` for a bare name (F6b) and `DETACHED_PROCESS`
behaviour (F13). Two Windows claims here **are** verified, by running them on this Mac rather than
asserting them: the cp1252 decode of the repo's own text files (F9), and CPython 3.11.5's Windows
`_execute_child` discarding `start_new_session` (`subprocess.py:1445`, F13). The POSIX side of every proposed change is a verbatim extraction of current code, so the
no-regression claim for macOS/Linux is high-confidence; the Windows side needs a real box or a
`windows-latest` CI leg to move from "documented" to "verified."

---

## Appendix — review history

- **Round 1, inventory-completeness lens** (`.switchboard/notes/reviewer-inventory-completene-inventory-gaps.md`):
  9 findings, all accepted. The systemic one: `defaults/` had never been swept by any of the six
  source audits. Also confirmed *held* under attack: `status.py` and `models.py` are clean; no
  `os.fork`/`setsid`/`killpg`/`resource`/`AF_UNIX`/`mkfifo`/`shell=True`/`PurePosixPath` anywhere;
  `os.pathsep` used correctly; the three `split("/")` sites split git-reported paths and are safe;
  `store.py`'s git path handling is Windows-safe; exactly one `sys.platform` branch
  (`stats.py:501`) and zero `os.name` in the whole package.

---

## Appendix — source audits
`.switchboard/notes/researcher-{process-liveness,locking-terminal,hooks-entrypoints,
worktree-filesyste,tui-rendering,herdr-integration}-findings.md` (gitignored; every `file:line`,
confidence level, and test note lives there).
