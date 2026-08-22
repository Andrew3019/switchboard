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
- **Cost 3 (NEW, round 2): the fleet CPU% number changes meaning.** `stats.py:438` reads
  `ps -Ao …,pcpu=` and `stats.py:454-457` documents those semantics *as a thing shown on screen*
  ("a decaying average over up to a minute of real time" on macOS). psutil has no equivalent:
  `Process.cpu_percent()` is CPU used *since the previous call on that Process object*, and
  `0.0` on the first call. Measured on this Mac: first call `0.0`, then `80.8` after a 0.4s busy
  loop, where `ps -o pcpu=` said `50.5` for the same pid. Two consequences the plan must carry:
  (a) the published number changes definition on macOS/Linux and the `stats.py` docstring must be
  rewritten with it; (b) a **stateless** `procscan` — fresh `Process` objects per sample, the
  obvious shape for a module serving three unrelated callers — makes fleet CPU% **`0.0` forever**.
  Keeping it non-zero requires per-pid `Process` objects retained across the collector's sample
  cadence (`stats.py:166`, behind `_PROC.get(...)`). That is a design constraint on `procscan`,
  not an implementation detail.
- **Cost 4 (NEW, round 2): the close gate's two-phase read is load-bearing.**
  `broker._live_under` (`broker.py:2443-2454`) reads the scan first and the process table
  *after*, and `broker.py:2437-2441` says the ordering is deliberate. `p.pid in parents` is a
  **liveness re-check** that exploits the gap between two independent reads: a pid the table no
  longer knows has exited. A `procscan` that serves both halves from **one enumeration** makes
  that test vacuously true, and processes that today drop out now count against the gate —
  **new refusals on macOS for a genuinely empty directory**. Safe direction, but the opposite of
  this plan's "the only semantic change is that false refusals get rarer". `procscan` must keep
  these as two separate reads, in that order. (The docstring's *stated* reason — lsof reporting
  itself — does dissolve under psutil; the liveness re-check does not.)
- **Cost 5 (NEW, round 2): psutil's output needs validating where lsof's was structurally safe.**
  `live._parse` (`live.py:106-107`) requires `name.startswith("n/")`, so an empty or relative cwd
  structurally cannot enter today's answer. psutil offers no such guarantee, and an empty cwd is
  not benign: `Path("").resolve()` is `os.getcwd()`, so `is_under("", checkout)` returns **True**
  whenever the broker's own cwd is under the checkout — the normal case for `sb workspace close`
  run from inside the workspace. One empty-cwd process anywhere on the machine ⇒ permanent
  refusal. macOS is safe today (a zombie raises `ZombieProcess`, verified) and Linux's
  `_pslinux.py` raises too, so this is a latent trap rather than a demonstrated break — but
  `procscan` must **reject any cwd that is not absolute**, not merely pass psutil's string on.
- **Cost 6 (NEW, round 2): the ppid map must be built from `ppid` alone.** Measured here:
  `psutil.process_iter(['pid','ppid'])` returns all 536 processes with **0 ppid mismatches**
  against `ps -Ao pid=,ppid=` — ppid is readable for foreign processes. But a *combined* fetch
  that also asks for e.g. `memory_info()` and drops `AccessDenied` entries loses 213 of 536.
  `_ancestry` (`broker.py:589-600`) walks to pid 1 through root-owned parents; a truncated map
  stops excluding the caller's own tree and the gate refuses to close a workspace the caller is
  standing in. Never combine the ppid fetch with a privileged attribute.
- **Cost 7 (NEW, round 2, cosmetic but user-visible): `Proc.command` changes on macOS.** lsof's
  `-F c` truncates at 31 chars; psutil's `name()` does not, and on macOS falls back to a
  cmdline-derived name. Measured: **17 of 277** names differ (`'VoiceMemosSettingsWidgetExtensi'`
  → `'VoiceMemosSettingsWidgetExtension'`, `'git-remote-http'` → `'git-remote-https'`). Surfaces
  in the close refusal (`broker.py:2312`) and `sb workspace list`'s `live[]`
  (`broker.py:1777`). Any test pinning a command string breaks.
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
| B1 | `broker.py:33`, `plugins.py:62`, `panel.py:69`, `sweep.py:44` | `import fcntl` (module-level) — 4 sites in `switchboard/`; see B7 for the 5th | route **8** lock calls through new `switchboard/lockfile.py` (D-below). The count matters: an earlier draft said "6" while listing 7 and missing `panel.py:478`, and converting all but one leaves `import fcntl` at `panel.py:69` — so Phase 1's "imports succeed on Windows" criterion still fails on `panel.py` while the entry reads done |
| B2 | `board.py:55,58` | `import termios` / `import tty` (also kills `richboard` via `from . import board`) | platform seam `switchboard/rawinput.py` |
| B3 | `collector.py:768`, `board.py:2414` | `signal.SIGHUP` referenced in a tuple — `AttributeError`, **not** caught by the `except ValueError`; crashes collector at startup / board on entry | guard with `hasattr(signal, "SIGHUP")` / platform filter |
| B4 | `board.py:2422` | `signal.signal(signal.SIGWINCH, …)` — `SIGWINCH` undefined on Windows | drop on Windows; replace with per-frame `os.get_terminal_size()` diff |
| B5 | `broker.py:3341-3356` (`_ready_pane`, called every spawn+restore at `:3693`,`:5375`) | types `export PATH=…:"$PATH"; echo "sb=$(command -v sb)"` — bash-only — into the pane; `wait_output` times out ⇒ `SbUnpinned` on **every** Windows agent | branch command by pane shell family (cmd/pwsh/posix), **defaulting to POSIX whenever the shell family is unknown**. Today `broker.py:3341-3356` emits one string with no detection of anything; after the change macOS's path depends on a new, unconfirmed herdr query (Phase 3 concedes "confirm herdr's API exposes it"). If that fact is unavailable — an older herdr, an adapter that does not implement it — and the dispatch lands anywhere but POSIX, **every macOS spawn times out into `SbUnpinned`**. §4's "the POSIX branch is byte-identical to today" pins the string but not the dispatch; both need a test. **Also branch the marker** at `broker.py:3348` — `marker = f"sb={bin_dir}/sb"` hardcodes both `/` and the extensionless name, and it is what `wait_output` matches. A branch that fixes the command and not the marker still times out into `SbUnpinned` |
| B6 | `bin/sb` + `hooks.py:113/126/143` + `bin/sb-stop-hook`/`sb-activity-hook` | extensionless shebang scripts; `sb` unlaunchable, Stop/activity hooks never fire (silently, "fails open") | D2 packaging + `.cmd` shims |
| B7 | `defaults/plugins/plans/__init__.py:379` (`import fcntl`), `:2869` (`flock` on the `_minting` id lock) | **The plans plugin dies silently on Windows.** `plugins._import` (`plugins.py:397`) catches `BaseException` and `load()` turns it into `status="broken"` — so `sb` does not crash, the plans plugin just answers "broken: No module named 'fcntl'" to every `sb plugin plans …`. That is the merge-gate machinery gone, reported only as a plugin health line. | route through `lockfile.py` — which needs **D5** first (a plugin cannot import `switchboard.lockfile` under today's contract) |

### Functional breaks — runs, produces wrong result or fails at use

| # | file:line | What | Fix |
|---|---|---|---|
| F1 | `live.py:61,89` | `lsof -a -d cwd -F pcn` — degrades safely to `None` on Windows (⇒ close always refuses) | D1 `procscan`/psutil |
| F2 | `stats.py:438` (`ps -Ao`), `stats.py:515` (`vm_stat`), `broker.py:2464` (`ps -Ao` in `_parents`) | POSIX-only process/memory subprocesses | D1; add `_available_windows()` to the `sys.platform` dispatch at `stats.py:501`. **RSS and `available` are safe** — both measured identical to psutil on this Mac (25952 KB exactly; `available` 0.9 MB apart, i.e. sampling skew). **CPU% is not** — see D1 cost 3; it is the one number whose definition changes |
| F3 | `board.py:2473` | `select.select([stdin_fd],…,0.25)` — Windows `select` rejects non-socket fds (`OSError`) | Windows branch: `msvcrt.kbhit()` polled on the same 0.25s cadence |
| F4 | `board.py:2395,2452,2406` | `termios.tcgetattr`/`tty.setraw`/`tcsetattr` raw-mode | Windows: `SetConsoleMode` + `ENABLE_VIRTUAL_TERMINAL_INPUT` via `ctypes`; keep `parse_sgr` shared |
| F5 | `broker.py:1116` | `symlink_to` no `target_is_directory`, no capability fallback | D4 |
| F6 | **4 sites:** `board.py:2217`, `collector.py:475`, `broker.py:415`, `defaults/plugins/plans/__init__.py:3573` (`_sb()`) | `os.access(path, os.X_OK)` — always True on Windows (no exec bit), then `subprocess.run` fails deep with `WinError 193` | **`os.name == "nt"`-gated; `os.access(X_OK)` stays verbatim on POSIX.** An *unconditional* swap to an existence check is a POSIX regression: all four sites read `str(own) if os.access(own, X_OK) else shutil.which("sb")`, so a `bin/sb` that exists but is not executable (`core.fileMode=false` checkout, a copy onto a share, a tarball export) today falls back to the installed `sb` and afterwards is returned and fails at `subprocess.run` with `PermissionError`. At `broker.py:415` that is worse than a failure — it pins a PATH dir whose `sb` cannot run, i.e. `SbUnpinned` on **every macOS spawn**. On Windows, check the `.cmd`/`.exe` shim's existence and invoke that path. Verified in the fix's favour: a `.cmd` **full path** does execute through `subprocess.run` (CreateProcess falls back to `cmd.exe` for `.bat`/`.cmd`), and `shutil.which` does consult `PATHEXT`. The break is the bare name, not the extension — see F6b |
| F6b | `defaults/plugins/report-bug/__init__.py:269` | `subprocess.run(["sb", "inspect", …])` — a **bare literal**, no `shutil.which`, no own-checkout resolution. Windows `CreateProcess` appends only `.exe` when searching PATH and does **not** consult `PATHEXT`, so under D2's committed-`.cmd`-shim path this never resolves and bug filing silently loses its pane-tail attachment | resolve through the same `_sb()`-shaped helper the other three sites use (arguably a POSIX cleanup too — it is the only unresolved `sb` in the repo) |
| F7 | `hooks.py:113/126/143`, `broker.py:3343` | `shlex.quote` — POSIX quoting; breaks on Windows paths with spaces | branch on `os.name`; use `subprocess.list2cmdline`/`"..."` for Windows, keep `shlex.quote` for POSIX |
| F7b | `hooks.py:157` (`p.read_text()`), `:160` (`tmp.write_text(body)`) | the **same two lines** write Claude Code's `settings.json` with no `encoding=`. Claude Code reads that file as UTF-8; this writes it in the ANSI code page. A checkout path with any non-ASCII character produces a settings file Claude Code mis-parses or reads a wrong path out of — and hooks never fire, silently | `encoding="utf-8"` on both. Part of the F9 class, called out separately because the consequence is "hooks are dead", not "text looks wrong" |
| F8 | `board.py:2269` | `prompt_pane(…, "exec {python} -m switchboard.board")` — `exec` is a POSIX builtin | drop `exec` on Windows panes (not load-bearing) |
| F9 | **A package-wide class, not two lines.** No text read in this codebase passes `encoding=`. On Windows `Path.read_text()`/`open()` fall back to `locale.getpreferredencoding(False)` — the ANSI code page, cp1252 on a default install, not UTF-8 (3.11/3.12; UTF-8 mode is only the default from 3.15). The grep is `grep -rn -e 'read_text(' -e '.open(' -e 'write_text(' switchboard/ defaults/`, minus the lines that already pass `encoding=`. Sites: `board.py:2179`, `output.py:337`, `defaults/plugins/plans/__init__.py:3848` (the three `errors="replace"` opens); `config.py:163` (`read_toml`), `:191` (`read_text`), `:425`, `:453`; `models.py:213`; `presets.py:167`, `:220`; `plugins.py:336`; `store.py:108`/`:118`; `sweep.py:313`/`:319`; `panel.py:136`/`:145`; `broker.py:1134`, `:4090`; `collector.py:568`; `defaults/plugins/plans/__init__.py:3350`; and F7b | **Silent corruption of the artefact switchboard exists to produce.** Measured, not assumed: `defaults/protocol.md` (192 non-ASCII bytes) and `defaults/settings.toml` (293) both decode *successfully* as cp1252 into mojibake (`'sessions â€” in this repo'`). `config.py:191` is what reads `protocol.md`, every role `.md` and `agent.md` — i.e. **every agent's spawn prompt is mojibake on a default Windows install**. `read_toml` corrupts any setting *value* containing `—`/`’`. Contrast `herdr.write_prompt_file` (`herdr.py:145,147`), which already passes `encoding="utf-8"` — which is why this is a gap and not the whole codebase | add `encoding="utf-8"` at every site. Zero-risk on POSIX (it is what a UTF-8 locale already does) and it fixes the same **latent POSIX bug** under `LC_ALL=C` / minimal containers |
| F10 | `board.py:2333` write path | no `sys.stdout.reconfigure(encoding="utf-8")` ⇒ glyphs (`✗◐◌○●`) raise `UnicodeEncodeError`/mojibake on a non-UTF-8 codepage | **`sys.stdout.reconfigure(encoding="utf-8", errors=sys.stdout.errors)`, guarded** — see the F10/F11 hazard note below. A bare `reconfigure(encoding=…)` is **not** zero-risk on POSIX and **is not** what the rest of the F9 class is |
| F11 | `bin/sb-stop-hook:28`, `bin/sb-activity-hook:27` — `hooks.run(sys.stdin.read())` | the **read** side of F10. `sys.stdin` decodes a pipe with the ANSI code page and `errors='strict'`. `0x81 0x8D 0x8F 0x90 0x9D` are undefined in cp1252, so a payload containing e.g. `●` (UTF-8 `E2 97 8F`) raises `UnicodeDecodeError` before `json.loads` runs. Both scripts catch it and return 0 — hooks fail open by design (B6) — so the Stop gate silently never fires for that turn and nothing is logged | `sys.stdin.reconfigure(encoding="utf-8", errors=sys.stdin.errors)`, guarded. **Phase 1 patches the two `bin/` scripts directly** — `hooks_entry.py` is a Phase 2 artifact and this fix must not wait for it; Phase 2 carries it across when it folds the two scripts. Same hazard note |
| F12 | 26 `subprocess.run(..., text=True)` sites across `switchboard/` and `defaults/` (e.g. `defaults/plugins/report-bug/__init__.py:269`, `plans/__init__.py:3556`, `plans/analysis/evidence.py:110`) | `text=True` with no `encoding=` decodes the child's stdout with the ANSI code page too. Reading `sb … --json` output containing an em-dash gives mojibake through `json.loads`, or a `UnicodeDecodeError` on the undefined cp1252 bytes | pass `encoding="utf-8"` alongside `text=True`. Same class as F9, same zero-risk POSIX fix. *(Found while verifying F9; not in the round-1 findings.)* |
| F13 | `panel.py:583` `start_new_session=True` (the collector spawn, `panel.py:576-586`) | **was V6, and V6's verdict was wrong.** V6 said CPython maps this to `CREATE_NEW_PROCESS_GROUP` on Windows. It does not: CPython 3.11.5's Windows `_execute_child` takes it as `unused_start_new_session` (`subprocess.py:1445`) and never reads it; the docstring at `:785` says "POSIX only". It is **silently discarded** — no `creationflags` are set. This is the repo's single elected collector, and `start_new_session` is what detaches it from whichever renderer won the election. On Windows it stays in that renderer's console and process group: a Ctrl-C in that pane, or closing that console window, takes the fleet's collector down and every panel goes stale | Windows branch adding `creationflags=DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP`; keep `start_new_session=True` unchanged on POSIX |

**The F10/F11 hazard — two ways a bare `reconfigure(encoding=…)` regresses macOS/Linux.**
Measured on this Mac under the repo's live `LANG=C.UTF-8`:

1. **It silently flips the error handler to `strict`.** `TextIOWrapper.reconfigure(encoding=…)`
   with no `errors=` resets `errors` to `strict`. CPython uses `surrogateescape` for stdio
   whenever the locale is `C`/`POSIX`/`C.UTF-8`, which is exactly what this repo's agent panes
   run under — `sys.stdout.errors` is `surrogateescape` today and `strict` after the change
   (`LANG=en_US.UTF-8` gives `strict` either way, so this is locale-dependent, not universal).
   Consequences: a lone surrogate in a board frame — the usual source is `os.fsdecode` on a path
   with undecodable bytes, which reaches `board.py:2333` through the checkout/workspace paths the
   board prints — prints today and raises `UnicodeEncodeError` after. On the read side the hooks
   catch it and return 0, so the **Stop gate silently stops firing on macOS** — the exact failure
   mode F11 exists to fix on Windows, reintroduced on POSIX. *(The handler flip is measured; that
   a lone surrogate reaches either call site today is not — no end-to-end repro was built.)*
2. **`reconfigure` does not exist under captured stdout.** `redirect_stdout(io.StringIO())` /
   pytest's `capsys` replace `sys.stdout` with a `StringIO`, which has no `reconfigure` —
   `AttributeError`, on every platform, at board startup.

So both calls must pass `errors=` explicitly (preserve with `errors=sys.std*.errors`, or make a
deliberate documented choice) **and** be guarded with `getattr(sys.stdout, "reconfigure", None)`.
Note the contrast with the rest of the class: F9 and F12 really *are* POSIX no-ops — under
`LANG=C.UTF-8`, `locale.getpreferredencoding(False)` is already `UTF-8` and `read_text` /
`subprocess(text=True)` already use `errors='strict'`, so adding `encoding="utf-8"` changes
nothing. `sys.std*` is the one place CPython does *not* default to strict, which is why F10/F11
are different and must not inherit F9's "zero-risk on POSIX" line.

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
  `fcntl.flock` extracted verbatim. **8 call sites, from `grep -n flock switchboard/*.py defaults/plugins/plans/__init__.py`:**
  `plugins.py:687`, `sweep.py:308`, `panel.py:435`, `panel.py:453`, `panel.py:474`,
  **`panel.py:478`** (`collector_running`'s release — missed by the first two drafts),
  `broker.py:2863`, and `defaults/plugins/plans/__init__.py:2869` (reachable only once **D5**
  says how, see B7). Do not convert "all but one": one survivor keeps `import fcntl` at module
  scope and B1 is not done. Windows branch = `msvcrt.locking` at offset 0 after `os.lseek(0)` (must lock
  the *same* byte range at all sites to contend). ~40 lines; recommended over a `portalocker`
  dep. All 8 lock calls are whole-file, advisory, exclusive, cross-process, on a *separate* 0-byte
  `.lock` file (never the data file) — so Windows *mandatory* byte-range locking never collides
  with the separate `tmp + os.replace` data rewrite. Checked in the API's favour (round 2): `lock(fd, *, blocking)` / `unlock(fd)` keeps the fd with
  the caller, which is what `panel.acquire`'s "the fd IS the lock" contract (`panel.py:426-430`)
  requires — a path-taking API would have been a real POSIX regression. One rule to preserve: never read a `.lock`
  file's contents from a second process without holding the lock (works by accident on POSIX,
  `PermissionError` on Windows).
- **`switchboard/rawinput.py`** — the raw-mode keypress seam. POSIX = `termios`/`tty`/`select`
  unchanged. Windows = `ENABLE_VIRTUAL_TERMINAL_INPUT` + `msvcrt.kbhit()` polling. **Keep
  `parse_sgr` (`board.py:139`) as the single shared parser** — only the byte *source* forks.
- **`switchboard/procscan.py`** (D1 = psutil) — one *module* serving `live.scan`, `stats`
  memory/process sampling, and `broker._parents`. **Not one enumeration** — round 2 showed that
  phrasing was itself the bug. Four rules it must hold, each from a measured macOS behaviour
  (D1 costs 3–6):
  1. The cwd scan and the ppid read stay **two separate reads, in that order**. The gap between
     them is the close gate's liveness re-check (`broker.py:2443-2454`).
  2. The ppid map is built from **`ppid` alone** — never a combined fetch that could drop an
     `AccessDenied` process and truncate `_ancestry`.
  3. Any cwd that is **not absolute** is rejected, reproducing the `n/` guard at `live.py:107`.
     An empty cwd resolves to the broker's own and refuses the gate forever.
  4. CPU% needs **per-pid `Process` objects retained across samples**, or it reads `0.0` forever.
- **`switchboard/hooks_entry.py`** — one module replacing the two duplicated hook scripts.

---

## 3. Phased implementation plan

Every phase is written as "add a Windows branch," never "rewrite the POSIX one." Ordering is by
dependency: nothing downstream can be tested on Windows until the import-time blockers clear.
**The code-dependency graph 0→1→2→3→3b→4→5→6→7 was attacked in review round 3 and held** — no
phase's *code* needs a later phase's code. What round 3 broke was the exit criteria: five of them
were unsatisfiable, or green over the exact failure the phase exists to prevent. They are rewritten
below, and every phase now states what it changes in `.github/workflows/tests.yml`.

**Phase 0 — settle what gates code.** Three questions, none of them coding work:

- **D5 (how a plugin reaches `lockfile`)** — open, gates B7, which is in Phase 1.
- **H1 — does herdr run natively on Windows, and does it make a Windows pane?** `herdr.py:1-11`:
  herdr is an external binary pinned to **0.8.0 / protocol 19**, and it is the only thing that
  makes a pane. Phases 3, 3b, 6 and V3/V5 all presuppose a native Windows herdr. **Nothing in this
  plan or in the six audits establishes that.** The herdr-integration audit asserts it in a
  parenthesis — "herdr itself is not being changed (already Windows-native)" — with no evidence,
  and the same audit later says the Windows install location is unknown ("once the actual Windows
  install location is confirmed from herdr's own installer docs"). If the answer is no, Phases 1,
  2, 4 and 5 all land and pass their gates and switchboard still spawns nothing on Windows — this
  plan's signature failure mode, a green check over a dead subsystem, at plan scale. **Andrew is
  the one who can answer this.** Also settle the install-dir fallback it decides (M3).
- **H2 — does herdr's API report what shell a pane runs?** B5's dispatch needs it (Phase 3). If
  herdr cannot say, B5's whole design changes, and §2's B5 row has the blast radius: a dispatch
  landing anywhere but POSIX is `SbUnpinned` on **every macOS spawn**. Same kind of question as
  H1 and answered in the same conversation; it is a decision, not a Phase 3 bullet.

**Phase 1 — make it import on Windows (unblocks all testing).**
- `lockfile.py` shim. **The counts, from `grep`, because an earlier draft of this plan got them
  wrong twice:** `switchboard/` has **4** `import fcntl` and **7** `flock` calls; `defaults/` adds
  **1** and **1**. Convert all **8** call sites — `plugins.py:687`, `sweep.py:308`,
  `panel.py:435/453/474/478`, `broker.py:2863` (B1), and `plans/__init__.py:2869` (B7, via whatever
  D5 decides). Do not convert "all but one": one survivor keeps `import fcntl` at module scope and
  the first exit criterion still fails. Pure extraction on POSIX.
- `rawinput.py` seam so `board.py`/`richboard.py` import without `termios`/`tty` (B2).
- Guard `SIGHUP` (B3) and `SIGWINCH` (B4) with `hasattr`/platform filters in `collector.py` and
  `board.py`.
- Add the whole F9 encoding class now, plus F7b, F12, and F10/F11 **with their `errors=` +
  `getattr` guards** (cheap, mechanical, and each also fixes a latent POSIX bug under a
  non-UTF-8 locale). **F11 patches `bin/sb-stop-hook:28` and `bin/sb-activity-hook:27` directly
  here** — `hooks_entry.py` does not exist until Phase 2, and Phase 2 carries the fix across when
  it folds the two scripts. Saying so because §2's F11 row points at the Phase 2 artifact.
- CI: add `windows-latest` to the matrix **with `continue-on-error: true`**, and register the
  `windows`/`posix` pytest markers. Both were previously scheduled into Phase 2's `pyproject.toml`,
  which is too late — Phase 1 is the phase that first needs Windows skips, and without
  `continue-on-error` the new leg is red on every unrelated PR in the repo from Phase 1 to Phase 7.
  Markers can live in `pytest.ini`/`setup.cfg` now and move into `pyproject.toml` at Phase 2.
- Exit criteria:
  1. `import switchboard.*` succeeds on `windows-latest`; pytest *collects*.
  2. `grep -rn "import fcntl\|import termios\|import tty" switchboard/ defaults/` returns nothing
     outside the new seams — the mechanical check that (1) is not passing by accident.
  3. **`python bin/sb plugin list` reports no shipped plugin as `broken`.** Three corrections to
     the earlier wording, all measured: it is **`python bin/sb`**, because `bin/sb` is unlaunchable
     on Windows until Phase 2 and there is no `switchboard/__main__.py`; it is **"none broken"**,
     not "every plugin `ok`", because `defaults/plugins.toml:61` ships `todo` **off** and
     `plugins.py:425-426` gives a disabled plugin `status="not enabled"` — the old criterion was
     unsatisfiable on a healthy Mac today, and an unsatisfiable gate gets loosened ad hoc, which is
     where B7 gets lost again; and the check must **grep the output**, because `cli.py:1411`
     returns `0` unconditionally. This still catches B7: `plugins.py:429`'s `broken()` overwrites
     `"not enabled"`, and `load_all` (`plugins.py:488-492`) imports every available plugin
     regardless of enablement. Without this criterion, (1) and (2) pass with the plans plugin —
     and the merge gate — silently dead, which is exactly how B7 was missed.

**Phase 2 — make `sb` runnable and hooks fire (B6, D2).**
- `pyproject.toml` console-scripts + `hooks_entry.py` (carrying Phase 1's F11 fix) + committed
  `.cmd` shims. Move the pytest markers here.
- Fix `hooks.py` quoting (F7's `hooks.py` half) and `_entry_point` to return the `.cmd`/entry path
  on nt. **F7's `broker.py:3343` half belongs to Phase 3**, absorbed by B5's `_ready_pane` rewrite —
  F7 is not done at the end of this phase.
- Replace the 4 `os.access(X_OK)` checks (F6) with shim-existence checks **behind an
  `os.name == "nt"` gate**, keeping `os.access` verbatim on POSIX; resolve `report-bug`'s bare
  `"sb"` literal (F6b).
- CI: add an install step. `tests.yml` today runs `pip install --upgrade pip pytest` and no
  `pip install -e .`, and its header comment asserts there is nothing to install. `sb.exe` does
  not exist without one.
- Exit criteria — **split, because these are not one phase's worth of provability**:
  1. *CI, this phase:* `python bin/sb --help` runs on `windows-latest` through the committed
     `.cmd` shim (needs no install), and `pip install -e .` produces an `sb` entry point on all
     three OSes.
  2. *Deferred to Phase 7, and say so:* "a registered Stop hook actually fires" needs a real
     Claude Code install on native Windows. §4's own "cannot be pinned in CI" list already
     contains Claude Code's hook runner (V4). Phase 2 cannot gate on it; pretending otherwise is
     the "Phases 1–5 are CI-verifiable" claim overreaching.

**Phase 3 — make agent spawn work (B5, F8, F7's `broker.py` half).** Gated on **H1 and H2**.
- Branch `_ready_pane` (B5, including the marker at `broker.py:3348`) and `board.open_beside` (F8)
  by pane shell family, **defaulting to POSIX when the family is unknown**. Do not infer from the
  Python process's platform — pane shell is a herdr/OS property.
- Exit criteria: (a) CI, all OSes — the builder emits today's byte-identical POSIX string when the
  herdr shell-family fact is absent; (b) hands-on — an agent spawns and pins into a Windows pane.

**Phase 3b — collector detachment (F13).** Windows `creationflags` on the `panel.py:583` spawn.
Gated on H1. Small, but it is the difference between one elected collector and a collector that
dies with a console window. Exit criterion: closing the electing renderer's console leaves the
collector up (hands-on; no CI path).

**Phase 4 — process/liveness backend (D1, F1/F2).**
- `procscan.py` (psutil), holding the four rules in §2. Repoint `live.scan`, `stats`,
  `broker._parents`.
- **`procscan` must fail loudly if psutil is missing.** `panel.py:578-587` spawns the collector
  with `stderr=subprocess.DEVNULL`, so on any interpreter without psutil the collector dies into
  `/dev/null` and the panel just goes stale — B7's exact shape, reintroduced on macOS by this
  phase. `stats.py:497-499` rejected psutil originally for this precise reason ("a dependency the
  collector's interpreter is not promised"). Surface the missing dep as a panel-visible state, not
  a silent death.
- Add `_available_windows()` to the `stats` memory dispatch.
- Rewrite `stats.py:454-457`'s `%CPU` docstring: the number's definition changes (D1 cost 3).
- Fix the `live.py` docstring + `is_under` NTFS case-fold at **`live.py:136`** (M6); remove the bogus
  `tests/test_live.py` Linux skip and add a static-fixture parse test.
- CI: `psutil` joins the install step. **This phase, not the matrix change, is what can turn the
  existing ubuntu and macOS legs red** — `tests/test_live.py` and `tests/test_stats.py` import the
  repointed modules, and without an install step every existing leg fails at import. §4's
  "additive, no risk to existing legs" was true of adding an OS and was never a statement about
  adding a required dependency.
- Exit criteria — worded to fail on D1's own predicted failures, because "populate" and "answers
  correctly" are both green over them:
  1. Fleet CPU% is **non-zero across two consecutive collector samples** (D1 cost 3: a stateless
     `procscan` reads `0.0` forever, and `0.0` is a populated number).
  2. `sb workspace close` **actually closes an empty workspace** (D1 cost 5: the empty-cwd trap
     makes the gate refuse forever, and refusal is the fail-safe at `broker.py:2305` — a check
     that only confirms "refuses while an agent is live" is green over a permanently dead gate).
  3. The existing ubuntu and macOS legs are still green.

**Phase 5 — worktree filesystem (D4, F5, M5).**
- `symlink_to` → `target_is_directory` + junction/copy fallback; update the two `is_symlink`
  detection sites in lockstep.
- Exit criteria — **two, one per branch**, because the old single criterion tested only the path
  Andrew will not use:
  1. *The path Andrew actually runs (D4's primary):* on a Developer-Mode box, a fresh worktree gets
     a real symlink, created with `target_is_directory` correct for the directory target, and
     **both** `is_symlink()` sites (`broker.py:1113`, `:1856`) classify it as ours (M5).
  2. *The fallback:* on an unprivileged box, `.switchboard` is a working junction and `CLAUDE.md`
     a copy, and the same two detection sites classify **those** as ours. Note this branch is
     **not reachable on GitHub's `windows-latest`** — those runners are elevated, so `os.symlink`
     succeeds and the fallback never executes. §4's mocked `OSError(1314)` unit test is the only
     CI coverage it can have.

**Phase 6 — interactive board input/render (F3, F4, V3).** Gated on H1.
- Wire `rawinput.py`'s Windows byte source into the read loop; `SetConsoleMode` VT-enable at
  startup (gated); SIGWINCH→poll.
- Exit criteria: the board draws and takes keys inside a herdr Windows pane. (Least
  CI-verifiable — largely hands-on.)

**Phase 7 — polish + verify.** M1–M4, M6; run the V1–V5 smoke tests on a real box; run Phase 2's
deferred Stop-hook check (V4); drop `continue-on-error` from the `windows-latest` leg; update the
README "Status" disclaimer.

**What is actually CI-verifiable.** Phases 1 and 4 are, once their install steps land. Phase 2 is
half (the shim, not the hook). Phase 3's *dispatch default* is; its pane behaviour is not. Phase
3b, Phase 5's fallback branch, and Phase 6 are hands-on only — there is no herdr and no tmux on any
runner, which `tests.yml`'s own header already says for POSIX. The earlier claim that "Phases 1–5
are largely CI-verifiable" was too broad.

---

## 4. Testing & CI strategy

- **`tests.yml` needs three edits, in three different phases, and no phase used to own any of
  them.** The file today installs `pip pytest` and nothing else, runs `python -m pytest tests` with
  **no `pip install -e .`**, and its header comment states the premise out loud: *"switchboard has
  no dependencies beyond the standard library — no requirements.txt, no pyproject.toml, nothing to
  install but the test runner."* So:
  - **Phase 1** adds `windows-latest` to the matrix, `continue-on-error: true` on that leg, and the
    `windows`/`posix` markers. The matrix change *is* additive and safe — `fail-fast: false` is
    already set, and there are no caches, artifacts or matrix-wide steps for a new OS to collide
    with. That is the whole of what "additive, no risk to existing legs" ever covered.
  - **Phase 2** adds an install step (`pip install -e .`), without which D2's `sb.exe` does not
    exist and half of Phase 2's gate is unprovable.
  - **Phase 4** adds `psutil`. **This is the edit that can turn the existing ubuntu and macOS legs
    red**, and it is a change to the same file's premise, not to its matrix: `tests/test_live.py`
    and `tests/test_stats.py` import the modules Phase 4 repoints, so the moment psutil becomes
    required and is not installed, every existing leg fails at import. The header comment has to be
    rewritten in the same commit — it will no longer be true.
  - Phase 7 drops `continue-on-error`.
  First Windows failures, in order: (1) collection-time import errors (B1–B4) blank the suite until
  fixed; (2) `lsof`/`ps`/`vm_stat` tests need Windows skips or the psutil backend; (3)
  mocked-`Herdr` tests should pass once imports clear; (4) any `bin/sb`-execution tests fail until
  Phase 2.
- **Register `windows`/`posix` pytest markers** (Phase 1, in `pytest.ini`/`setup.cfg`; moved into
  `pyproject.toml` at Phase 2 — they cannot start there, because Phase 1 is the phase that first
  needs Windows skips) instead of ad-hoc
  `skipif(sys.platform…)` scattered around, so "what runs only on Windows" is one grep. Mirrors
  the existing `tests/test_live.py` skip precedent.
- **High-value tests that need no Windows box** (write these regardless of when the port lands):
  - Command-string builders parameterized on shell family — assert the Windows branch never emits
    a bare single-quoted path, and the POSIX branch is **byte-identical to today** (pins the
    no-regression guarantee). Covers F7, hooks, and **B5's POSIX half and dispatch default only**.
    It does *not* cover B5's Windows half: "never emits a bare single-quoted path" is a shape
    assertion, and whether the emitted cmd/pwsh string actually pins PATH and echoes something
    `wait_output` matches needs a real Windows shell. The thing that decides `SbUnpinned` is the
    branched **marker** (`broker.py:3348`) matching what the pane really prints — un-pinnable in
    CI, and listed in §5 as unproven.
  - `_entry_point()` returns a `.cmd` path under monkeypatched `os.name == "nt"`.
  - `link_config` falls back to copy when `os.symlink` raises `OSError(1314)` (D4).
  - `live._parse` accepts the captured GNU-lsof 4-line fixture (kills the bogus skip).
  - Encoding: transcript read + glyph write round-trip under a forced non-UTF-8 locale (F9/F10) —
    reproducible on any OS. Extend it to the **spawn-prompt path** (`config.read_text` →
    `defaults/protocol.md`), which is the site where the corruption actually costs something.
  - **The round-2 no-regression pins, all runnable on macOS today** — these are the ones that
    would have caught the five regressions the "verbatim extraction" claim hid:
    - `reconfigure` under `LANG=C.UTF-8` leaves `sys.stdout.errors` unchanged, and board startup
      does not raise under `capsys` (F10/F11 — both defects, both measured).
    - `_entry_point`-family: under monkeypatched `os.name == "posix"`, a non-executable `bin/sb`
      still falls through to `shutil.which` (F6's POSIX half, byte-identical to today).
    - `_ready_pane` emits today's exact string when the herdr shell-family fact is **absent**
      (B5's dispatch default, not just its string).
    - `_live_under` still drops a pid that vanished between the scan and the ppid read
      (D1 cost 4 — fake a `procscan` whose two reads disagree).
    - `procscan` rejects a non-absolute cwd (D1 cost 5) and builds ppid maps from `ppid` alone
      (D1 cost 6).
    - fleet CPU% is non-zero across two consecutive collector samples (D1 cost 3 — the stateless
      shape reads `0.0` forever and no existing test would notice).
  - `python bin/sb plugin list` reports **no shipped plugin as `broken`** — a regression test for
    B7's failure mode, where a plugin import error is swallowed into a health line nobody reads.
    Runs on every OS. Must grep the output: `cli.py:1411` returns `0` unconditionally. Not "every
    plugin `ok`" — `todo` ships disabled (`defaults/plugins.toml:61`) and reads `not enabled`, so
    that wording is unsatisfiable on a healthy Mac today.
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
unproven on Windows: msvcrt byte-range lock on an empty file; `ENABLE_VIRTUAL_TERMINAL_INPUT` delivering SGR
sequences; the msvcrt raw-byte read (V5); psutil's Windows cwd/`AccessDenied` (D1); ConPTY VT
(V3); WAL sidecars (V1); `os.replace` mid-read share modes and whether CPython's Windows `open()`
grants delete-sharing (V2 — unverified in *both* directions, not "very likely fine"); Claude Code's
hook-runner shell (V4); `CreateProcess` ignoring `PATHEXT` for a bare name (F6b) and `DETACHED_PROCESS`
behaviour (F13).

**The largest unproven claim in this document is one it used to not mention at all: that herdr
runs natively on Windows and makes a Windows pane (H1).** herdr is an external binary pinned to
0.8.0 / protocol 19 (`herdr.py:1-11`) and it is the only thing that makes a pane, so Phases 3, 3b
and 6 and V3/V5 all rest on it. The only claim anywhere is an unevidenced parenthesis in the
herdr-integration audit ("already Windows-native"), and that same audit does not know where a
Windows herdr installs. Nothing here verifies it. **H2** — whether herdr's API reports a pane's
shell family — is unproven in the same way and decides B5's design. Both are Phase 0 questions
for Andrew.

Also unproven, from review round 3: that B5's Windows command string is one a real cmd/pwsh pane
accepts and echoes a `wait_output`-matchable marker for (the CI test covers the shape and the
POSIX default, not this); and whether D2's `@py -3` shim resolves through the Windows launcher
rather than the interpreter `actions/setup-python` chose — if it does, anything exercised *through*
the shim on `windows-latest` is not testing the matrix's 3.11/3.12 axis. The reviewer who raised
that had no Windows box and did not verify it; a shim spelled `python "%~dp0sb"` instead of
`py -3` would sidestep it without reopening D2. Two Windows claims here **are** verified, by running them on this Mac rather than
asserting them: the cp1252 decode of the repo's own text files (F9), and CPython 3.11.5's Windows
`_execute_child` discarding `start_new_session` (`subprocess.py:1445`, F13). **The zero-regression claim is per-item, not blanket.** An earlier draft said "the POSIX side of
every proposed change is a verbatim extraction of current code" — round 2 showed that is false for
five of them, and two of those change macOS behaviour on Andrew's own machine. Where it stands now:

| change | POSIX effect | evidence |
|---|---|---|
| B1/`lockfile`, F3, F4, F7, F8, B5's *string*, F5/D4's `target_is_directory` | verbatim extraction / a fork POSIX never enters | read, not run |
| F9, F12 | true no-op | measured: under `LANG=C.UTF-8` these already use UTF-8 + strict |
| `broker._parents` → psutil | behaviour-preserving | measured: 536 procs, 0 ppid mismatches |
| psutil cwd set, RSS, `available` | behaviour-preserving | measured: 0 cwd strings differ; RSS identical; `available` 0.9 MB apart |
| **F10, F11** | **regresses macOS** unless `errors=` is passed and the call guarded | measured: `surrogateescape` → `strict`; `AttributeError` under capture |
| **F6** | **regresses macOS** unless `os.name`-gated | read: a non-executable `bin/sb` stops falling back |
| **B5's dispatch** | **regresses macOS** unless absence-of-fact defaults to POSIX | the herdr fact is unconfirmed (Phase 3) |
| **D1 CPU%** | **changes a published number's definition**, and reads `0.0` forever if `procscan` is stateless | measured: `ps` 50.5 vs `cpu_percent()` 0.0 then 80.8 |
| **D1 close gate** | **new refusals** if one enumeration serves both halves of `_live_under` | read: `broker.py:2437-2454` documents the ordering as deliberate |
| D1 `Proc.command` | user-visible string changes, cosmetic | measured: 17 of 277 names differ |

Every one of those regressions has a fix written into its §2 entry and a test in §4. The Windows
side still needs a real box or a `windows-latest` CI leg to move from "documented" to "verified."

---

## Appendix — review history

- **Round 1, inventory-completeness lens** (`.switchboard/notes/reviewer-inventory-completene-inventory-gaps.md`):
  9 findings, all accepted. The systemic one: `defaults/` had never been swept by any of the six
  source audits. Also confirmed *held* under attack: `status.py` and `models.py` are clean; no
  `os.fork`/`setsid`/`killpg`/`resource`/`AF_UNIX`/`mkfifo`/`shell=True`/`PurePosixPath` anywhere;
  `os.pathsep` used correctly; the three `split("/")` sites split git-reported paths and are safe;
  `store.py`'s git path handling is Windows-safe; exactly one `sys.platform` branch
  (`stats.py:501`) and zero `os.name` in the whole package.

- **Round 2, zero-regression / psutil-blast-radius lens**
  (`.switchboard/notes/reviewer-zero-regression-psutil-blast-radius.md`): 8 findings, all
  accepted, all re-verified here by running them. It broke the plan's blanket no-regression
  sentence (now the table in §5) and found five proposed changes that regress macOS. Also
  confirmed *held*: `broker._parents`, the psutil cwd set, RSS and `available` are all
  behaviour-preserving on macOS by measurement; F9/F12 are true POSIX no-ops; F7 and F3 are clean
  forks; the `lockfile(fd)` signature respects `panel.acquire`'s "the fd IS the lock" contract.

- **Round 3, phase-ordering / testability lens**
  (`.switchboard/notes/reviewer-phasing-testability-phase-ordering.md`): 13 findings, all accepted.
  §3 was rewritten around them. The attack did **not** land on the ordering — the code-dependency
  graph held, as did D5's placement and the completeness of the B1–B4 import-blocker set. It landed
  on the exit criteria (five were unsatisfiable or green over the failure they exist to catch), on
  the CI story (three `tests.yml` edits across three phases, none previously owned; the "additive,
  no risk" line only ever covered the matrix change), and on **H1/H2** — a herdr-on-Windows
  assumption four phases rested on and the plan never named.

---

## Appendix — source audits
`.switchboard/notes/researcher-{process-liveness,locking-terminal,hooks-entrypoints,
worktree-filesyste,tui-rendering,herdr-integration}-findings.md` (gitignored; every `file:line`,
confidence level, and test note lives there).
