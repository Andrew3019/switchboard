# Windows audit — herdr integration, pane commands, env vars, CLI entry, CI/packaging

Scope: `switchboard/herdr.py`, `switchboard/cli.py`, `switchboard/config.py`, the pane-priming
path in `broker.py` that calls into `herdr.py` (`_ready_pane`, `_own_sb_bin`), CI/packaging.
All findings verified by reading current code on this branch, 2026-08-22. Nothing executed on
a real Windows box — herdr itself is not being changed (already Windows-native); this only
covers what switchboard hands it.

## Headline: `_ready_pane` types a bash/zsh-only command into every agent pane

**`switchboard/broker.py:3341-3356`** (`Broker._ready_pane`), reached from `_ready_pane` calls
at `broker.py:3693` and `broker.py:5375` — i.e. **every spawn and every restore**, before
`herdr.start_agent` ever runs. When the checkout has its own `bin/sb` (true for switchboard's
own worktrees, and for any project that vendors one), the command sent into the pane via
`Herdr.prompt_pane` (`herdr.py:839-856`, which does `pane run` + `send-keys enter`) is:

```python
command = f'export PATH={quoted}:"$PATH"; echo "sb=$(command -v sb)"'
```

(`broker.py:3347`, `quoted = shlex.quote(str(bin_dir))` at `3343`). Every piece of this is
POSIX shell syntax with no Windows equivalent typed into the pane's actual shell:

- `export VAR=val` — a bash/zsh builtin. cmd.exe uses `set VAR=val`; PowerShell uses
  `$env:VAR = val`. Neither understands `export`.
- `:"$PATH"` — POSIX PATH-entry separator is `:`; Windows' is `;`. Also `$PATH` is bash/zsh
  variable syntax; cmd.exe wants `%PATH%`, PowerShell wants `$env:PATH`.
- `$(command -v sb)` — POSIX command substitution + the `command` builtin. cmd.exe has no
  equivalent; PowerShell does support `$(...)` subexpressions but not `command -v` (that
  would be `Get-Command sb`).
- `shlex.quote()` (`broker.py:3343`, and again in `hooks.py`, see below) always emits
  POSIX/shell quoting (single-quotes-with-`'\''`-escaping) regardless of host OS — it has no
  Windows mode. A path fed through it and then typed into cmd.exe or PowerShell is not
  correctly quoted for either.

**What breaks on Windows:** the pane never echoes the `sb=...` marker (syntax error instead),
`wait_output` (`herdr.py:858`) times out after `PIN_MS`, every attempt in
`for attempt in range(PIN_ATTEMPTS)` (`broker.py:3357`) fails, and the spawn raises
`SbUnpinned`/`PaneNotReady` (`broker.py:3372-3376`) for every single agent. **This is the
first-order blocker**: nothing downstream (the actual `agent start` call in
`herdr.start_agent`) is even reached.

The `bin_dir is None` fallback (`broker.py:3355`, `echo "sb-rea""dy={name}"`) is closer to
portable — `echo` exists in cmd.exe and PowerShell too — but the split-string trick is a POSIX
concatenation idiom (avoiding echoing the literal marker in the typed line); it happens to
still work as plain text in cmd.exe/PowerShell too, so this branch is not blocking, only the
PATH-pin branch is.

**Latent Linux bug:** none found here — this command is valid POSIX and runs the same on
bash/zsh on Linux and macOS. The break is Windows-only.

**Recommended fix.** This needs a per-shell-family command, chosen from the pane's platform
(herdr's `pane` object / `tab create` response should say what OS it's running on — worth
confirming with herdr's own docs/API; if not exposed, switchboard's own `platform.system()`
of the *herdr host* is not sufficient since a pane's shell family is a herdr/OS property, not
a Python-process property — this needs a herdr-reported fact, not an assumption). Concretely:
- POSIX pane (bash/zsh): keep the existing command.
- cmd.exe pane: `set PATH={dir};%PATH%\r\necho sb={dir}\sb` (cmd.exe has no reliable inline
  `&&`-safe quoting story for paths with spaces; `set` also does not support `$()`-style
  substitution, so the marker there can't assert "the shell resolved sb" the same way —
  it can only assert "the shell echoed what we told it", which is a weaker but still useful
  proof-of-life).
- PowerShell pane: `$env:PATH = "{dir};$env:PATH"; Write-Output "sb=$(Get-Command sb
  -ErrorAction SilentlyContinue)"`.
- Use `os.pathsep`-equivalent per target shell (`;` vs `:`), never hardcode `:`.
- Do **not** reuse `shlex.quote` for a Windows-shell string — it will misquote. Either hand-roll
  minimal quoting (Windows paths rarely need it beyond wrapping in `"..."`, but `%`/`$`
  expansion rules differ between cmd and PowerShell too) or use `subprocess.list2cmdline`-style
  escaping *only* as a reference for cmd.exe argument quoting — it is not a general answer
  for `set`/`$env:` statements.

**Test implications:** the shell-syntax generation itself (which string gets built for which
shell family) is unit-testable without a Windows box — feed a fake "platform" flag into
`_ready_pane` and assert the exact string. The end-to-end "does cmd.exe/PowerShell actually
accept it and print the marker" cannot be verified without a real Windows pane (or at minimum
a Windows VM running herdr) — CI cannot prove this even with `windows-latest`, since there is
no herdr/tmux equivalent on the runner (confirmed already true for POSIX — see the tests.yml
comment at the top of the file, "no herdr and no tmux on the runner").

## `board.open_beside` — a second bash-only command through the same `prompt_pane`

**`switchboard/board.py:2269`**:
```python
h.prompt_pane(pane, f"exec {sys.executable} -m switchboard.board")
```
`exec` is a bash/zsh builtin ("replace this shell with the following command") with no cmd.exe
or PowerShell equivalent — cmd.exe would report `'exec' is not recognized...`, PowerShell would
report `exec: command not found` (or similar). This is outside my assigned file (`board.py`),
but it goes through the same `Herdr.prompt_pane` I audited (`herdr.py:839-856`), so flagging it
here as directly relevant to "what shell-shaped strings does switchboard hand herdr". Fix
would drop the `exec` for a Windows pane (just run `{sys.executable} -m switchboard.board`
directly — the `exec`-replaces-the-shell behavior is a POSIX nicety, not load-bearing;
`prompt_pane`'s caller ignores whether the shell was replaced or a child was spawned).

## `Herdr` itself: clean, but one POSIX-flavored fallback

**`switchboard/herdr.py:239`**:
```python
self.binary = binary or shutil.which("herdr") or str(Path.home() / ".local/bin/herdr")
```
`shutil.which("herdr")` is genuinely cross-platform — on Windows it consults `PATHEXT` and
would find `herdr.exe`/`herdr.cmd` on PATH correctly. The **fallback** (`~/.local/bin/herdr`)
is a Linux/macOS install convention; it is not wrong to leave it (it's a pure fallback, only
consulted when `herdr` is not on PATH at all), but it will never resolve anything real on
Windows, where herdr's installer more likely places the binary somewhere under
`%LOCALAPPDATA%` or similar. Low priority — recommend making this fallback
platform-conditional (`if os.name == "nt": <Windows herdr install dir> else: ~/.local/bin/herdr`)
once the actual Windows install location is confirmed from herdr's own installer docs. Not a
regression risk either way since `shutil.which` almost always wins first.

**Duplicate of the same fallback**: `switchboard/store.py:962` — same expression, same
reasoning, deliberately not imported from `herdr.py` (see the docstring there, "the two-line
duplication is the price of the layering"). Both need the same fix, kept in sync.

**Everything else in `herdr.py` is clean for Windows**: every `subprocess.run` call
(`_run` at `herdr.py:213-214`, `read_pane` at `herdr.py:911-914`) passes a real argv list —
no `shell=True`, no manual string joining into a shell command — so there is no POSIX-vs-cmd.exe
quoting problem *within this module*. The `--append-system-prompt-file` mechanism
(`_prompt_flags`, `herdr.py:473-515`) writes a real file via `Path.write_text`/`.replace()`
(`write_prompt_file`, `herdr.py:131-155`) — that's `pathlib`, fully portable, no `os.rename`
raciness concerns beyond what already applies on Windows (`Path.replace` is atomic-enough
there too, same as POSIX, per Python docs). No `fcntl`/`termios`/POSIX-only imports anywhere
in this file.

One more thing worth flagging for the CI/packaging plan rather than as a bug: `_call`
(`herdr.py:268-312`) and `_spawn` (`herdr.py:246-266`) assume `proc.stdout`/`proc.stderr` are
`str` (via `text=True` at `_run`, `herdr.py:214`) — this is fine on Windows too (Python's
`subprocess` with `text=True` decodes using the platform default, which on Windows can be a
different codepage than UTF-8 if the herdr binary emits non-ASCII; herdr's JSON output is
presumably always UTF-8/ASCII though — worth a smoke check once a Windows herdr binary is
available, not a code change today).

## Env vars

Audited every read of `HERDR_PANE_ID`, `HERDR_WORKSPACE_ID`, `SB_DEBUG`, `SWITCHBOARD_*`,
`NO_COLOR` across the package (not just my three files, since env reads are scattered):

- `HERDR_PANE_ID` — `broker.py:722`, `hooks.py:194` (both `os.environ.get(...)`, no POSIX
  assumption; herdr sets this itself in the pane's environment on any platform per the brief).
- `HERDR_WORKSPACE_ID` — `broker.py:3230`, same shape, same verdict.
- `SB_DEBUG` — `cli.py:754`, `cli.py:1405` (`os.environ.get("SB_DEBUG")`) — plain truthiness
  check, portable.
- `SWITCHBOARD_DEFAULTS` — `config.py:48,75-76` (`ENV_DEFAULTS`), used as
  `Path(env).expanduser()` — fully portable, `pathlib` handles a Windows-style path string
  fine as long as the user supplies one appropriate to their OS.
- `SWITCHBOARD_MODELS_CONFIG` — `models.py:102`, not read in my three files but same pattern
  (grep confirms only `models.py` reads it) — did not fully audit `models.py`'s use, but the
  name alone (`ENV_GLOBAL_CONFIG`) suggests the same `Path(...)`-based handling as
  `ENV_DEFAULTS`; flag for whichever researcher owns `models.py` to confirm.
- `NO_COLOR` — `board.py:120`, `richboard.py:142` — outside my scope's files but trivially
  portable (`os.environ.get("NO_COLOR") is None`).

**No `os.environ["HOME"]` or `os.environ.get("HOME")` read anywhere in the package** — grepped
the whole `switchboard/` tree. Every place that needs the user's home directory uses
`Path.home()` (`herdr.py:239`, `store.py:962`, and others found by grep), which is already
cross-platform (`Path.home()` resolves `USERPROFILE` on Windows, not `HOME`). **This
contradicts the prior-findings note's framing** ("`os.environ['HOME']` which is
`%USERPROFILE%` on Windows" was listed as a category of risk in `_prior-findings.md` — I found
no actual instance of it in this codebase; the prior note appears to have been describing a
generic risk pattern rather than a citation. Worth the lead confirming with whoever wrote it,
but as read today, `HOME` is a non-issue.)

**`PATH`** — read only via `shutil.which(...)` (`herdr.py:239`, `store.py:962`, `board.py:2217`,
`collector.py:475`) and constructed for the *pane's* shell in the `_ready_pane` command above
(the actual Windows-breaking case). `shutil.which` itself is cross-platform-correct.

## `switchboard/cli.py` — entry point and dispatch

- **`if __name__ == "__main__":`** at `cli.py:1526` — plain, portable, no assumption.
- **`main(argv=None)`** at `cli.py:625` — argparse-based, no shell interaction, no path
  separators assumed. Portable as-is.
- **`flush_pending`** (`cli.py:680`) calls into `broker.flush_pending`, which is pure DB +
  herdr-adapter logic — no subprocess/shell string building happens in `cli.py` itself. The
  actual pane-command construction lives in `broker.py`/`herdr.py`, covered above.
- **How it locates `python`/`sb`**: `cli.py` itself does not resolve `sb`'s own location — that
  happens in `bin/sb` (see next section) before `cli.main` is ever called. `cli.py` has no
  `sys.path` manipulation of its own.
- No other platform branches, no `os.fork`, no signal handling, no POSIX-only imports in
  `cli.py`. Clean.

## CLI entry point / packaging: `bin/sb` is the real Windows blocker for "can `sb` even run"

**`bin/sb`** (repo root, not under `switchboard/`):
```
#!/usr/bin/env python3
import sys, os
sys.path.insert(0, ...)
from switchboard.cli import main
raise SystemExit(main())
```
No extension, relies entirely on the POSIX shebang line + the executable bit (`chmod +x`,
implicit in git as the file mode) for `./bin/sb` or a PATH-resolved `sb` to run at all.
**Windows has no shebang-line execution and no executable-bit concept for arbitrary files.**
`CreateProcess`/`cmd.exe`/PowerShell can only directly launch files with recognized extensions
(`.exe`, `.bat`, `.cmd`, or extensions registered via `PATHEXT`/file association — `.py` is
sometimes registered to the Python launcher `py.exe` if installed with "Add python.exe to
PATH" + `.py` association, but an **extensionless** file named `sb` is not launchable by
Windows process creation under any of those mechanisms). Concretely, on Windows,
`subprocess.run(["path/to/bin/sb", ...])` raises `OSError: [WinError 193] %1 is not a valid
Win32 application`, and typing `sb` at a cmd.exe/PowerShell prompt with `bin/` on PATH does
nothing (`'sb' is not recognized...`) unless a `.cmd`/`.exe`/`.bat` shim also exists.

This same extensionless-shebang shape is reused for the two hook scripts,
**`bin/sb-stop-hook`** and **`bin/sb-activity-hook`** (both confirmed by reading them — same
`#!/usr/bin/env python3` header, no extension), which matters doubly because **the exact
command string that invokes them is built in `switchboard/hooks.py`**, squarely in my brief's
"env vars"/"CLI entry" territory even though the file itself is `hooks.py`:

**`switchboard/hooks.py:135-141`** (inside `settings_file`):
```python
db = shlex.quote(str(store.db_path(cwd)))
...
"command": f"{shlex.quote(str(activity))} --db {db}",
...
"command": f"{shlex.quote(str(gate))} --db {db}",
```
where `activity`/`gate` are `_entry_point("sb-activity-hook")` / `_entry_point()` →
`Path(__file__).resolve().parent.parent / "bin" / "sb-stop-hook"` (`hooks.py:100-101`) — an
**absolute path to the extensionless script**, quoted with `shlex.quote` (POSIX quoting,
regardless of host OS). These strings are written into Claude Code's own `--settings` JSON
as the literal shell command for the `UserPromptSubmit`/`Stop` hooks
(`hooks.py:126-163`, `stop_hook_args` at `hooks.py:165-175`, wired into every spawn via
`herdr.py:571-573`, `agent_args += hooks.stop_hook_args()`). Two independent problems stack
here for Windows:
1. `shlex.quote` emits POSIX single-quote escaping — wrong quoting for however Claude Code's
   hook runner invokes a `"command"` string on Windows (likely via `cmd.exe /c` or direct
   `CreateProcess` — either way, POSIX single-quotes are not meaningful).
2. Even correctly quoted, the target itself (`bin/sb-stop-hook`, no extension) is not
   Windows-launchable per the `bin/sb` problem above — the hook would need to be invoked as
   `python bin/sb-stop-hook` (or `python.exe`/`py`) explicitly, not as a bare path.

**Recommended fix — the packaging one that resolves all three of these at once:** add a
`pyproject.toml` with a `[project.scripts]` (setuptools/PEP 621 `console_scripts`-equivalent)
entry, e.g.:
```toml
[project.scripts]
sb = "switchboard.cli:main"
sb-stop-hook = "switchboard.hooks_entry:stop_hook_main"
sb-activity-hook = "switchboard.hooks_entry:activity_hook_main"
```
`pip`/`pipx` installing this generates a real Windows launcher (`sb.exe`, a tiny generated
`.exe` shim that embeds the interpreter call) for each entry, solving the "extensionless
shebang file is not launchable" problem uniformly across `sb` itself and both hook scripts,
on all three platforms, with **zero behavior change on macOS/Linux** (the existing `bin/sb`
etc. can stay as-is for the "run in place, no install" workflow the README describes — a
`pyproject.toml` is additive, not a replacement, unless the team wants to also deprecate the
bin/ scripts). This directly answers the brief's question ("whether a `pyproject.toml` with a
`sb` console entry point is the clean packaging answer") — **yes**, and it's the only fix that
also solves the hook-script-launchability problem without hand-rolling per-shell-family
command strings in `hooks.py` (the console-script shim handles "how do I run a Python
entrypoint on this OS" once, centrally, instead of every caller reasoning about shebangs).
The `shlex.quote` POSIX-quoting issue in `hooks.py` still needs an independent fix even after
this — the *command string itself* (`f"{quoted_path} --db {db}"`) needs to become
platform-aware quoting once the target is `sb-stop-hook.exe` rather than a bare script path
(spaces in a Windows install path are the main remaining risk — `"..."` double-quoting is the
Windows convention for both cmd.exe and PowerShell single-argument quoting, not
`shlex.quote`'s POSIX single-quotes).

**Where `bin/sb` is invoked directly as an executable (all break the same way on Windows,
all need the console-script fix above, or an explicit `sys.executable` prefix as a stopgap):**
- `switchboard/board.py:2217,2221` (`_inspect`, checked via `os.access(own, os.X_OK)` then
  `subprocess.run([sb, ...])`)
- `switchboard/collector.py:475,` used at the `_run_sb` call site around `collector.py:440-448`
  (`doorbell_sb`, same `os.access(..., os.X_OK)` pattern)
- `switchboard/broker.py:400-415` (`_own_sb_bin`, feeds the PATH-pin command in `_ready_pane`
  above — also returns a directory whose `bin/sb` won't run without an interpreter prefix or
  a generated shim)

Note: `os.access(path, os.X_OK)` on Windows does **not** reliably mean "this is launchable" —
Windows has no execute-permission bit for arbitrary files, so `os.access(..., X_OK)` on
Windows generally just checks the file exists (per CPython's implementation, `X_OK` on
Windows is treated the same as `F_OK`/existence for ordinary files). So all three call sites
above would find `bin/sb` "executable" on Windows and then fail at the `subprocess.run(...)`
step with `WinError 193`, not fail early/cleanly at the access check. That makes the failure
mode worse (a confusing native OS error deep in a `subprocess.run`, not a clean "not found"),
which is itself worth fixing regardless of the console-script approach — e.g. checking
`sb.with_suffix(".exe").exists()` or similar on Windows, or just always going through the
console-script shim once it exists so this whole `os.access(X_OK)` idiom can be retired.

**Latent Linux/macOS bug:** none — this whole shape (shebang + chmod +x) works correctly and
identically on Linux and macOS today; the break is Windows-only.

**Test implications:** the string-building parts (what command gets constructed for which
target OS) are unit-testable without a Windows box by parameterizing on a fake `os.name`/
platform flag and asserting the generated command text. Whether a generated `.exe` shim
actually launches, and whether Claude Code's own hook runner correctly invokes a `"command"`
string on Windows, cannot be verified without a real Windows install of both `pip`-installed
switchboard and Claude Code — that's an integration-test-on-real-Windows item, not something
CI can prove even with `windows-latest` added (no Claude Code, no herdr on the runner either).

## `switchboard/config.py`

No herdr-binary-location logic lives here at all (that's `herdr.py`/`store.py`, both flagged
above) — `config.py` only reads `.toml`/`.md` files under `defaults/` and `<repo>/.switchboard/`
via `pathlib`. Every path in this file is built with `Path(...)  /  "segment"` (e.g.
`config.py:52,79,88,103`) — **zero hardcoded `/`-string-joins found** (`grep -n '"/"'` etc.
returned nothing in this file). `pathlib`'s `/` operator is platform-correct on Windows too
(uses `\`, or accepts `/` transparently — `PureWindowsPath` normalizes both). `defaults_dir()`
(`config.py:73-76`) resolves `SWITCHBOARD_DEFAULTS` via `Path(env).expanduser()` — portable.
**No platform branches exist in this file today** (the brief asked whether any already exist —
none do), and none are needed for `config.py` itself: it is clean for Windows as written.

One thing worth flagging for whoever designs the CI Windows matrix: `config.py:41`
(`import tomllib`) is Python-3.11+ stdlib, same story on Windows as elsewhere — no additional
risk here, just confirming the `tomllib` floor from `tests.yml`'s own comment applies equally.

## CI / packaging plan

**Current matrix** (`.github/workflows/tests.yml:24-33`): `ubuntu-latest` (3.11, 3.12) +
`macos-latest` (3.11 only, "the platform switchboard is actually used on, where nothing
skips" per the file's own comment). No Windows leg exists.

**Adding `windows-latest` — expected first failures, in the order they'd actually bite:**
1. **Collection-time import errors** — `fcntl`/`termios` imports in `broker.py`, `plugins.py`,
   `panel.py`, `sweep.py`, `board.py` (outside my scope's files, per the prior-findings note
   and confirmed still present by grep during this audit) would fail `import switchboard...`
   outright for any test that imports those modules — this is a pytest collection error, not
   a test failure, so it would likely blank out large swaths of the suite rather than
   producing individual red tests. This has to be fixed (or those imports made conditional /
   isolated behind platform guards) before a Windows leg produces any signal at all beyond
   "collection failed."
2. Once collection succeeds (imports guarded), tests that shell out to `lsof`/`ps`/`vm_stat`
   (`live.py`, `stats.py` — not my files) would fail or need Windows-specific skips.
3. Tests that exercise `herdr.py`/`broker.py`/`hooks.py` behavior with a **mocked** `Herdr`
   (the `runner` injection point at `herdr.py:235`, `Runner = Callable[..., CompletedProcess]`)
   should mostly still pass on Windows once the above imports are fixed, since the mock
   doesn't care what shell is underneath — the actual command-string content (the
   `_ready_pane` string, the `hooks.py` command string) is exactly the kind of thing that
   *should* get platform-parameterized unit tests asserting the Windows-shaped string, run
   on `windows-latest` alongside the existing POSIX-shaped assertions on the other legs.
4. Any test relying on `bin/sb`/`bin/sb-stop-hook`/`bin/sb-activity-hook` being directly
   executable (if any exist — did not find one in my scoped files, worth the QA/test-focused
   researcher checking `tests/`) would fail per the packaging section above, until the
   console-script fix lands.

**Gating plan:** standard `pytest.mark.skipif(sys.platform == "win32", ...)` /
`skipif(sys.platform != "win32", ...)` markers, mirroring the existing pattern already used
for the Linux `lsof`-shape skip the prior-findings note cites (`tests/test_live.py:76`) — that
precedent already establishes the house style for this, so no new mechanism is needed, just
more markers. Recommend a `windows` and `posix` marker registered in `pytest.ini`/`pyproject.toml`
(once one exists) rather than ad hoc `skipif(sys.platform==...)` scattered everywhere, so a
grep for "what only runs on Windows" is one command.

**No regression risk to the existing POSIX legs** from adding a Windows leg with `fail-fast:
false` (already set, `tests.yml:26`) — a new matrix entry is additive; the existing
`ubuntu-latest`/`macos-latest` legs are untouched by anything above unless the *production*
code changes (e.g. making the `_ready_pane` command platform-aware) — and every fix proposed
above is written as "add a Windows-shaped branch," never "change the POSIX-shaped one," so
the macOS/Linux path stays byte-for-byte identical.

## README "Status" section

`README.md:175-180`: "It is personal software: it assumes one human, one machine, herdr on
the PATH, and Claude Code as the agent. There is no packaging story, no cross-platform
testing..." — accurate as read; matches every finding above. Once a `pyproject.toml`
console-script lands and a Windows CI leg is green, this section is the natural place to
update the disclaimer (not fixing it now, per the brief — read-only).

## Spotted elsewhere (not chased, outside this brief's scope)

- `fcntl`/`termios` imports (`broker.py:33`, `plugins.py:62`, `panel.py:69`, `sweep.py:44`,
  `board.py:55,58`) and the `flock`/`tcgetattr`/`tcsetattr` call sites the prior-findings note
  names — confirmed still present, not re-audited in depth (belongs to whichever researcher
  has locking/terminal-raw-mode in scope).
- `board.py:2414`, `collector.py:768`: `signal.SIGHUP` — not available on Windows
  (`AttributeError` at import/reference time on `signal.SIGHUP`); `board.py:2422`:
  `signal.SIGWINCH` — also POSIX-only. Both outside my scoped files but directly relevant to
  whoever owns `board.py`/`collector.py`.
- `live.py`'s `lsof -F pcn` BSD-vs-Linux parse bug — already documented in
  `_prior-findings.md`, confirmed still present by the presence of the Linux skip in
  `tests/test_live.py:76`, not independently re-verified in depth (outside my scope's files).
- Worktree symlinks (`broker.py:1116` per prior-findings, `paths.linked_config`) — not
  re-verified, outside my scoped files.
