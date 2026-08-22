# Windows audit: Claude Code hooks, `sb` entrypoints, quoting/spawning

Scope: `switchboard/hooks.py`, `bin/sb*`, and every place that builds a shell command
string or spawns a subprocess. Read the whole of `hooks.py` and all three `bin/` scripts;
grepped `shlex`, `subprocess`, `os.system`, `shell=True`, `#!/usr/bin/env`, `sys.executable`
across `switchboard/` and `bin/`.

## 1. `hooks.py` — the hook command strings are POSIX shell text

`settings_file()` (`switchboard/hooks.py:91-162`) writes two hook commands into the
per-repo Claude Code settings JSON:

- `switchboard/hooks.py:126` — `f"{shlex.quote(str(activity))} --db {db}"` for
  `UserPromptSubmit`.
- `switchboard/hooks.py:143` — `f"{shlex.quote(str(gate))} --db {db}"` for `Stop`.
- `switchboard/hooks.py:113` — `db = shlex.quote(str(store.db_path(cwd)))`, reused in both.

Two independent breakages, not one:

**(a) `shlex.quote` output is POSIX-shell syntax.** `shlex.quote` wraps a path containing
special characters in single quotes (`'...'`) and escapes embedded ones. That is correct
for bash/zsh, meaningless for `cmd.exe`, and wrong for PowerShell (which uses backtick or
double-quote escaping, not single-quote-with-`'\''`-style escaping). A Windows path like
`C:\Users\andrew\repo\bin\sb-stop-hook` has no shell metacharacters `shlex` cares about, so
`shlex.quote` happens to pass it through *unquoted* today — but the moment that path
contains a space (`C:\Users\andrew\My Repo\bin\sb-stop-hook`, a completely normal Windows
path shape via OneDrive-redirected `Documents`, `Program Files`, etc.), `shlex.quote` wraps
it in single quotes, which `cmd.exe` treats as literal characters, not quoting — the
resulting command string breaks in two tokens.

**(b) The command names a bare path with no interpreter and no extension.** Both
`_entry_point()` calls (`switchboard/hooks.py:81-88`) resolve to `bin/sb-stop-hook` and
`bin/sb-activity-hook` — files with a `#!/usr/bin/env python3` shebang and no extension.
On macOS/Linux the shebang plus the executable bit (`chmod +x`, done once at checkout time
— not verified as automated anywhere in this repo) is what lets the OS exec them directly.
Windows has no shebang interpretation for a bare `CreateProcess` call (only WSL/Git-Bash
environments parse `#!`), and Claude Code's own hook runner is very likely to invoke the
`command` string via the platform shell rather than `execve`-ing it directly — either way,
a bare extensionless path is not runnable on native Windows. There is no `.cmd`/`.bat`/
`.ps1` wrapper anywhere in `bin/`, and nothing generates one.

Net: **on native Windows, neither hook fires.** The Stop gate (the mechanism the whole
protocol depends on — `sb done`/`sb block` enforcement) silently never runs, which by the
file's own "fails open" design (`hooks.py:44-46`) means agents can end turns with no report
and nobody is told, because the intended signal is a Claude Code hook error the file itself
never sees. That is worse than the file's documented failure modes (unreadable payload,
missing store) because those still *attempt* to run; a bare non-executable path never gets
a process at all — it should show as a Claude Code hook error in the transcript, but nothing
in switchboard verifies or surfaces that.

**Not a latent Linux bug** — `shlex.quote` + a `chmod +x` shebang script is the textbook
correct POSIX pattern, and this path is exercised on both today's CI platforms
(`ubuntu-latest`, `macos-latest` per prior findings).

## 2. `bin/sb`, `bin/sb-stop-hook`, `bin/sb-activity-hook` — shebang scripts, no packaging

All three (`bin/sb:1`, `bin/sb-stop-hook:1`, `bin/sb-activity-hook:1`) open with
`#!/usr/bin/env python3` and do the same three-line dance: insert the repo root onto
`sys.path`, import, run. None of the three use `sys.executable` — they rely entirely on the
OS/shell resolving the shebang, i.e. on being POSIX-executed. Confirmed by
`README.md:103-111`: **there is no packaging file** ("no packaging file and nothing to
install switchboard *as*"; "`bin/sb` runs the checkout in place, under whatever `python3`
is on PATH").

Invocation paths, both broken on Windows as-is:

- **PATH symlink.** Prior findings record `~/.local/bin/sb` as a symlink to
  `<main checkout>/bin/sb`, created manually (I found no script in this repo that creates
  it — greeped for `.local/bin/sb` across `*.py`/`*.md`/`*.sh`, no hits, so this is a
  documented-but-manual step, not automated tooling to port). A POSIX symlink has no
  native Windows analogue that "just works": `os.symlink`/`mklink /D` need Developer Mode
  or admin, and even granted that, a symlink to an extensionless shebang file is still not
  directly runnable by `cmd.exe` (no shebang interpretation, and Windows resolves an
  executable by matching `PATHEXT` extensions — `sb` with no extension is invisible to
  `where sb` / bare invocation the way `sb.exe`/`sb.cmd`/`sb.bat`/`sb.ps1` would be).
- **Direct path.** `broker.py`'s `_ready_pane` puts `bin/` at the front of the spawned
  agent's `PATH` (see §3) so the agent's shell can just type `sb` — same `PATHEXT`
  problem on Windows: a bare `bin/sb` with no extension will not resolve via `PATH` lookup
  in `cmd.exe`/PowerShell no matter how it's placed on `PATH`.

`switchboard/broker.py:415`, `switchboard/collector.py:475`, and `switchboard/board.py:2217`
all gate "does this checkout ship its own runnable `sb`" on `os.access(path, os.X_OK)`.
**This is also a latent correctness gap surfaced by the Windows lens, worth flagging even
though it doesn't crash on POSIX:** `os.access(..., os.X_OK)` on Windows returns `True` for
any existing file regardless of whether it is actually executable (Windows has no execute
permission bit; CPython's Windows `os.access` implementation treats `X_OK` as equivalent to
`F_OK` for files). So on Windows these three checks would report "this checkout has a
runnable `sb`" even when `bin/sb` is a bare extensionless Python script nothing can exec —
the exact opposite of what the check exists to guarantee (`_own_sb_bin`'s docstring: "an
agent that falls back to the installed `sb` runs the MAIN checkout's code" — the whole
point is to *refuse* rather than silently run wrong code). Any Windows fix needs these
checks to test for something Windows can actually assert (e.g. presence of the resolved
shim file, or a `.exists()` check paired with the shim strategy below rather than X_OK).

**What has to change:**

1. **Packaging / console_scripts entry point** (the brief's suggested direction, and I
   agree it's the right one). Add a minimal `pyproject.toml` with a `[project.scripts]`
   entry (`sb = "switchboard.cli:main"`) and install in editable mode
   (`pip install -e .`). `pip`'s console-script generator writes a real `sb.exe` launcher
   on Windows (a tiny compiled stub that execs the right `python.exe` with the right
   script) and a POSIX shebang script on macOS/Linux from the *same* source — this is the
   one fix that removes the shebang/PATH-symlink dependency on **all three OSes**, not
   just Windows, and is a strict improvement (no more manual `~/.local/bin/sb` symlink to
   go stale, no more "whatever `python3` happens to be on PATH" ambiguity called out at
   `README.md:110` and `board.py:2295`). The two hook scripts should get the same
   treatment as their own entry points (`sb-stop-hook = "switchboard.hooks_entry:stop_main"`,
   `sb-activity-hook = "switchboard.hooks_entry:activity_main"`), or — simpler, and what
   the brief's key-questions section leans toward — collapse them into module entry points
   invoked as `python -m switchboard.hooks_entry --stop --db <path>` /
   `--activity --db <path>`, which sidesteps needing separate console-script shims for
   them at all (see §3).
   - **Regression risk on macOS/Linux: low.** `pip install -e .` console scripts are the
     standard, well-tested path; the existing `bin/sb` etc. can stay in the tree unchanged
     as a fallback/dev-convenience for anyone running from a bare checkout without
     installing — `_own_sb_bin`, `doorbell_sb`, and the board's editor-launch path
     (`broker.py:415`, `collector.py:475`, `board.py:2217`) already special-case "this
     checkout ships its own `bin/sb`" for the good reason documented at `broker.py:391-395`
     (run the branch's own code, not the installed build) and that logic can keep working
     unmodified on POSIX.
   - **Multi-checkout worktree model tension, worth flagging to whoever plans this:** the
     PATH-pin dance in `broker.py:3300-3360` exists specifically because every worktree
     needs to run *its own* checkout's code, not one globally-installed build
     (`broker.py:3310-3316`). A single global console-script install would reintroduce
     that exact bug ("a whole phase of fixes was acceptance-tested against code that was
     never running", `broker.py:384-385`) unless the Windows shim strategy is layered *on
     top of* the existing per-worktree PATH-prepend rather than replacing it — i.e. keep
     `_ready_pane`'s "put this checkout's bin dir at the front of PATH" behavior and make
     sure the bin dir on Windows actually contains something `PATHEXT`-resolvable
     (`sb.cmd` or `sb.exe`) per checkout, not just one machine-wide install.

2. **Per-checkout Windows shim, if avoiding a real package install per worktree.** Given
   the worktree tension above, the more surgical fix may be: keep `bin/sb`,
   `bin/sb-stop-hook`, `bin/sb-activity-hook` as the POSIX shebang scripts they are
   (untouched — zero POSIX regression risk), and add sibling `bin/sb.cmd`,
   `bin/sb-stop-hook.cmd`, `bin/sb-activity-hook.cmd` (or `.ps1`) generated at repo-checkout
   time (committed to git, like the `.py`/shebang files are) that do the Windows-native
   equivalent of the three-line shebang body — e.g. a `.cmd` shim of the form
   `@py -3 "%~dp0..\switchboard\hooks_entry.py" --stop %*` (using the `py` launcher, which
   ships with the official Windows Python installer, or falling back to
   `python "%~dp0..\switchboard\...`). `PATHEXT` includes `.CMD` by default, so
   `_ready_pane`'s PATH-prepend trick keeps working unmodified — a Windows agent typing
   `sb` resolves `sb.cmd` in the prepended `bin/` the same way a POSIX agent resolves the
   extensionless `sb`. This is the lower-regression-risk option since it changes nothing
   about how POSIX invokes the existing files; it only adds new files.

## 3. The concrete hook registration fix

Both problems in §1 need fixing together — quoting AND the interpreter/extension problem.
Concrete proposal, matching the brief's key-questions direction:

- Stop building a shell command **string** at all for the parts that vary per-OS.
  `shlex.quote` should be treated as POSIX-only from here on — it is fine for the parts of
  this codebase that only ever run inside a POSIX pane (see §4), but it must not appear in
  anything a Windows-hosted process executes directly.
- Register, per OS, a command Claude Code's hook runner can actually exec:
  - **POSIX (unchanged):** `f"{shlex.quote(str(gate))} --db {shlex.quote(str(db))}"` —
    exactly today's code, gated behind `if os.name == "posix"`.
  - **Windows:** either (a) the `.cmd` shim path from §2's option 2 — register
    `f'"{shim_path}" --db "{db_path}"'` (plain double-quoting is what `cmd.exe` actually
    honours for a path with spaces; `subprocess`/`CreateProcess`-style quoting, not
    `shlex`), or (b) if the console-script route from §2's option 1 is taken, register
    `python -m switchboard.hooks_entry --stop --db <path>` directly, using
    `sys.executable` resolved at settings-write time (not a hardcoded `python`/`python3` —
    see §5) and Windows `CreateProcess`-style double-quoting for any path with a space,
    not `shlex.quote`.
  - I'd recommend (b): it also kills the two separate `bin/sb-stop-hook` /
    `bin/sb-activity-hook` files' duplication (both do the identical "parse `--db`, call
    into `switchboard.hooks`, print JSON, always exit 0" dance) in favor of one
    `switchboard/hooks_entry.py` module with two thin functions, callable the same way via
    `-m` on every OS. This is a net simplification independent of Windows.
- **Whether Claude Code's hook runner itself uses `cmd.exe`, PowerShell, or execs
  directly is something I could not verify from this repo** — it's Claude Code CLI
  behavior, not switchboard's. This needs a real check against the current CLI (or a
  `claude-code-guide` lookup) before committing to a specific quoting scheme; the finding
  that stands regardless of which shell it turns out to be is that `shlex.quote` is wrong
  for either non-POSIX target.

## 4. `broker.py:3341-3348` — a second POSIX-shell command string, same family of bug

`_ready_pane`'s pin-verification step (`switchboard/broker.py:3300-3360`) builds and types
directly into the agent's pane:

```
switchboard/broker.py:3343:  quoted = shlex.quote(str(bin_dir))
switchboard/broker.py:3347:  command = f'export PATH={quoted}:"$PATH"; echo "sb=$(command -v sb)"'
```

This is bash/zsh syntax end to end: `export VAR=value`, `;` as a statement separator,
`"$PATH"`, and `$(command -v sb)` command substitution. None of it is valid in `cmd.exe`
(`export` isn't a command, `;` doesn't separate statements the same way, `$(...)` doesn't
exist) or PowerShell (`export` isn't a verb — needs `$env:PATH = ...`; `$(...)` exists but
with different semantics; `command -v` doesn't exist — the PowerShell equivalent is
`Get-Command`). Per this effort's brief, herdr already drives a native Windows shell
(`cmd.exe /d /c`) for spawned panes — so on a Windows agent, this string gets typed
verbatim into a `cmd.exe` or PowerShell prompt and does nothing useful; the pin-check would
either hang waiting for `wait_output`'s marker (`sb=<bin_dir>/sb`, itself POSIX-path-shaped)
or time out and refuse the spawn with `SbUnpinned` (`broker.py:388-396`) on every single
Windows agent start.

- **Fix:** branch this on the pane's shell family (herdr should expose, or switchboard can
  infer from the platform, which shell a spawned pane runs) and build the equivalent
  command per family:
  - `cmd.exe`: `set "PATH=<bin_dir>;%PATH%" & echo sb=` then a Windows `where sb` style
    check (`where` prints all matches on separate lines; the first line is what a bare
    `sb` invocation would resolve to) — or simpler, since the goal is just "prove `bin_dir`
    is now in front", skip the resolution round-trip and directly assert the shim file
    exists at `bin_dir` before typing anything, since Windows doesn't have `cmd.exe`'s
    exact `command -v` analogue in one portable line.
  - PowerShell: `$env:PATH = "<bin_dir>;$env:PATH"; "sb=$((Get-Command sb).Source)"`.
  - Keep the exact current POSIX line unchanged for POSIX panes — **zero regression risk**
    since it's gated on shell family, not rewritten.
- **This is squarely in the same "shell command string built as `f"..."` text" family as
  §1**, and both need the same underlying discipline going forward: prefer passing argv
  lists to `subprocess`/herdr's own spawn API with no shell involved wherever herdr's API
  allows it, and reserve hand-built shell strings (inevitable for the *pane-typing* case,
  since that's literally simulating a human typing into an interactive shell) for the
  minimum surface, each one explicitly branched per shell family rather than assumed-POSIX.
- **Not a latent Linux bug** — this is correct bash/zsh and every current CI/dev platform
  runs one of those as the pane shell.

## 5. `sys.executable` usage — mostly fine, one gap

Grepped every `sys.executable` and `python3` reference:

- `switchboard/sweep.py:339` — `[sys.executable, "-m", "switchboard.cli", "sweep"]`. Correct
  cross-platform pattern already.
- `switchboard/panel.py:579` — `[sys.executable, "-m", "switchboard.collector"]` for
  spawning the collector. Correct.
- `switchboard/board.py:2269` — `f"exec {sys.executable} -m switchboard.board"` typed into a
  pane. `exec` is a POSIX shell builtin (replaces the shell process rather than forking) —
  this is another instance of the §4 pattern (command text assumed to run in a POSIX
  shell), but lower urgency since it's an explicit "open the board in a new pane" action
  path, not the hook/spawn-verification hot path. Same fix shape as §4: branch on shell
  family, and on `cmd.exe`/PowerShell just drop the `exec` (there's no equivalent
  "replace this shell" builtin most users need — plain `<python> -m switchboard.board` is
  fine without it).
- **The gap:** `bin/sb`, `bin/sb-stop-hook`, `bin/sb-activity-hook` do **not** use
  `sys.executable` anywhere — they don't need to today, because the shebang line
  (`#!/usr/bin/env python3`) is what selects the interpreter on POSIX, and the script body
  never re-invokes Python itself. That's exactly why §2/§3's fix has to supply the
  interpreter explicitly for Windows (`sys.executable` resolved once, at the point
  something constructs the Windows-side command — either at settings-write time in
  `hooks.py`, or baked into a `.cmd` shim that calls `py -3` / a hardcoded `python.exe`
  lookup). Nothing in the current code hardcodes `python3` as a literal string anywhere in
  `switchboard/` — the only bare `python3` mentions are in comments/docstrings
  (`cli.py:113`, `board.py:2295`, `panel.py:674`), not executable code — so there's no
  existing hardcode to rip out, just a new interpreter-resolution step to add for the
  Windows entry points.

## Test implications

- **Quoting logic (`hooks.py` §1, `broker.py` §4) is unit-testable without a Windows box.**
  Once the fix branches on an explicit platform/shell parameter (rather than reading
  `os.name` inline), a test can call the command-building function with each shell family
  and assert on the resulting string — e.g. assert the Windows branch never emits a bare
  single-quoted path, assert the POSIX branch is byte-identical to today's output (pins the
  no-regression guarantee). This is the single highest-value test to add: it directly pins
  the exact bug this audit found.
- **Whether Claude Code's hook runner actually execs the registered command successfully
  on Windows cannot be tested without a real Windows box running the actual Claude Code
  CLI** — that's integration-level, outside what a fake/mock can stand in for credibly (the
  repo's own testing philosophy, per the common brief, already treats mocking external
  systems like this as the thing that burned this project before).
- **`os.access(X_OK)` behavior (§2) is a genuine Windows-only code path** — the existing
  POSIX test suite exercises the True/False split on real files with/without the exec bit;
  a Windows-specific test would need `sys.platform == "win32"` gating and can only run in
  CI on a `windows-latest` runner (not simulable on macOS/Linux, since the whole point is
  that Windows's `os.access` semantics differ from POSIX's).
- **The `.cmd`/console-script shim itself** is best pinned by a smoke test that actually
  invokes it as a subprocess and checks the exit code / stdout shape, which again needs a
  Windows runner — but the *content* of what gets written (the shim file's expected text,
  or the `pyproject.toml` entry-point declaration) is trivially unit-testable on any OS.

## Spotted elsewhere (not chased)

- `switchboard/panel.py:583` — `subprocess.Popen(..., start_new_session=True, ...)` when
  spawning the collector. I checked whether this raises on Windows: it does not — modern
  CPython (`subprocess.py`) maps `start_new_session=True` to
  `creationflags |= CREATE_NEW_PROCESS_GROUP` on the Windows branch of `_execute_child`
  rather than raising, so this specific call is fine as-is. Flagging only because it looked
  suspicious at first grep; verified it's a non-issue, didn't chase further since spawning
  in general belongs to whichever researcher covers process/collector lifecycle.
- `store.py`, `stats.py`, `broker.py`, `live.py`, `board.py` all call POSIX-only binaries
  (`git rev-parse` is fine — Git for Windows ships it — but `lsof`, `ps -Ao`, `vm_stat`,
  `herdr pane list` assumptions) via `subprocess.run` with argv lists (good — no
  `shell=True` anywhere in the repo, confirmed by grep and by `validate.py:24`'s own
  comment asserting it). The argv-list-not-shell-string discipline is already solid
  everywhere I looked outside `hooks.py` and `broker.py:3347`; the POSIX-only *tools*
  themselves (`lsof`/`ps`/`vm_stat`) are the prior researcher's stats/process concern, not
  mine — not re-auditing those here.
