# Windows audit: worktrees, symlinks, paths, filesystem/atomic-write semantics

Investigation only, 2026-08-22. No code changed. Verified against current code, not the
prior-findings doc (which is used only as a starting hint list per the brief).

## 1. Symlinks

### `broker.py:1116` — `dst.symlink_to(src)` (the only real symlink-creation site)
`Broker.link_config` (`broker.py:1096-1123`) links `LINKED_CONFIG =
("CLAUDE.md", ".switchboard")` (`defaults/settings.toml:82`, read via
`broker.py:71`) from the main checkout into every new worktree — a **file** symlink
(`CLAUDE.md`) and a **directory** symlink (`.switchboard`), in the same loop, both created
with the same call: `dst.symlink_to(src)` — no `target_is_directory` argument.

Two independent Windows problems, not one:
- **Privilege.** `os.symlink`/`Path.symlink_to` on Windows requires either Developer Mode
  (Win10 1703+) or an elevated process (`SeCreateSymbolicLinkPrivilege`). Neither is
  guaranteed on a fresh machine. This is already handled at the call site: `symlink_to` is
  wrapped in `try/except OSError` (`broker.py:1118-1119`) and logs `link_failed` rather than
  raising — so the *failure mode* is graceful today, but the *consequence* is severe: every
  spawn into a worktree silently loses `CLAUDE.md` (so Claude Code has no repo context) and
  `.switchboard` (so `.switchboard/briefs`, `.switchboard/notes`, `roles.toml`,
  `presets.toml`, `models.toml` are all invisible in that worktree — this exact
  `researcher-worktree-filesystem` brief file lives at a path that would not exist post-link
  on an unprivileged Windows box). Nothing downstream currently checks "did linking
  succeed" and degrades — `link_config`'s return value (list of what linked) is not
  consulted by callers to gate anything (`broker.py` calls it and moves on).
- **Wrong link type even when privileged.** `Path.symlink_to(target, target_is_directory=False)`
  defaults `target_is_directory` to `False`. On Windows the OS call underneath
  (`CreateSymbolicLinkW`) takes a `SYMBOLIC_LINK_FLAG_DIRECTORY` flag that must be set for a
  directory target — pathlib does **not** infer this from `target.is_dir()` in the CPython
  versions this repo targets (3.11/3.12; auto-detection only shows up in the Windows
  `os.symlink` fallback path for *relative* targets in some versions, and `src` here is
  passed as an absolute `Path` from `main / name`, `broker.py:1112`, so even that
  best-effort inference is not reliable). Left at the default, `.switchboard` — a directory
  — would be created as a *file*-type symlink, which Windows Explorer/cmd/most tools treat
  as broken/unusable even when Developer Mode is on and the call itself succeeds.

**Also latent on POSIX, mentioned for completeness (not a Windows-only bug):** none found —
`os.symlink`/`Path.symlink_to` on POSIX ignore `target_is_directory` entirely, so the
current code is correct there.

**Recommended fix**, does not regress POSIX:
1. Pass `target_is_directory=src.is_dir()` explicitly — free, correct on POSIX (ignored)
   and correct on Windows for both current entries.
2. Detect symlink capability once (try a throwaway symlink in a temp dir, or check
   `os.name == "nt"` and whether the create call raises `OSError` with `WinError 1314` —
   "a required privilege is not held") and **fall back to a real copy** for `CLAUDE.md`
   (cheap, correct — it's read-only reference material) and to a **directory junction**
   for `.switchboard` via `_winapi.CreateJunction` (junctions need no privilege on NTFS and
   work for directories; they cannot target files, which is why `CLAUDE.md` needs the copy
   fallback instead, not the junction fallback). A junction is *not* a symlink for
   `Path.is_symlink()` (junctions report `False`), so the two detection sites below
   (`broker.py:1113`, `:1856`) would need `is_symlink() or is_junction()` — Python stdlib
   has no `is_junction()`; `os.path.isjunction` was only added in Python 3.12, so on 3.11 it
   needs a manual `os.readlink`-style check or `FILE_ATTRIBUTE_REPARSE_POINT` via
   `os.stat().st_file_attributes`.
3. A plain **copy-and-diff-warn** fallback (copy once, and warn on `sb` commands if the
   worktree's copy has drifted from the main checkout's) is the simplest correct behavior
   if junctions are judged not worth the complexity — loses "exactly one true file", which
   `broker.py:69` calls out as the deliberate design, so this is a real regression in
   spirit, not just a Windows compromise; flag for a design decision rather than assuming it.

**Detection sites that must agree with whatever (1)-(3) above chooses:**
- `broker.py:1113` — `dst.exists() or dst.is_symlink()` decides whether to (re)link. A
  junction or a copy must also be recognized here or `link_config` will try to symlink over
  an existing copy/junction on every call and fail (harmlessly, since it's in the `except
  OSError` already, but noisily logging `link_failed` every time).
- `broker.py:1856` — `Path(path, entry).is_symlink()` decides whether an ignored file is
  "ours" (ownership bookkeeping in `_ignored_weight`, used by `workspace close`'s dirty-check
  gate, `broker.py:1825-1861`). If linking degrades to copy/junction on Windows, this check
  under-counts: a copied `CLAUDE.md` or a junctioned `.switchboard` would show up as
  `unknown` rather than `mine`, making `workspace close` on Windows report phantom
  uncommitted content and — because the close gate is deliberately fail-safe
  (`broker.py:2305`, `found is None` refuses) — could make close *more* cautious than
  necessary rather than actually unsafe. Low severity, but worth fixing in the same patch
  since it's the same list of names.

**Test implications:** the privilege/type behavior cannot be pinned without a Windows box
(or CI `windows-latest` runner, which does have Developer Mode-off by default — worth
checking whether GitHub's `windows-latest` image needs an explicit
`fsutil behavior set SymlinkEvaluation` or Developer Mode toggle step, or whether the
directory-junction fallback should just always be used on Windows so tests don't depend on
runner privilege at all). A platform-independent unit test *can* pin: "given a fake
`os.symlink` that raises `OSError(1314, ...)`, `link_config` falls back to copy and returns
success" — that tests the fallback logic without needing a real Windows filesystem.

### Other symlink-adjacent reads (no creation, just detection) — all fine as-is
- `broker.py:1113`, `:1856` — covered above, `is_symlink()` itself is portable and correct;
  only the *meaning* of "not a symlink" changes if a fallback strategy is added.
- No `os.symlink`, `readlink`, or `os.link` (hardlink) calls anywhere else in `switchboard/`
  or `bin/` — grepped the whole tree; `broker.py:1116` is the only symlink-creation site.

### `.switchboard/briefs` and `.switchboard/notes` — how they get created cross-platform
These are not linked individually. `.switchboard` itself is the one entry in
`LINKED_CONFIG` that is a directory (`defaults/settings.toml:82`), so the *whole directory*
is symlinked once by `broker.py:1116`, and `briefs/`, `notes/`, `roles.toml`,
`presets.toml`, `models.toml` all ride along for free as an implicit consequence of that one
link — they are never separately created, gitignored, or referenced by path elsewhere. This
means the fix above (junction for `.switchboard`) covers all of them in one place; there is
no second site to patch.

## 2. Path handling

### State-dir resolution — one hardcoded XDG default, wrong location on Windows (not a crash)
`defaults/settings.toml:66`: `user_state = "~/.local/state/switchboard"` — read by
`plugins.py:608` (`state_root`) via `config.setting("paths.user_state", ...)` and
`.expanduser()`. `Path("~/.local/state/switchboard").expanduser()` **works** syntactically
on Windows (`Path.home()` resolves via `USERPROFILE`, and pathlib accepts `/`-separated
literal directory names fine) — so this is not a hard break, but it plants a
`.local\state\switchboard` tree under the user's home directory instead of the Windows
convention (`%LOCALAPPDATA%\switchboard` or `%APPDATA%\switchboard`). Every tool that
respects Windows conventions (antivirus exclusions, roaming-profile backup, "clean my
temp/cache files" utilities) will not know to treat it specially, and a user following
Windows norms would not find it. `store.py:962` and `herdr.py:239` also hardcode
`~/.local/bin/herdr` as a fallback when `shutil.which("herdr")` fails — same category, not a
crash (falls through to a `str` that then fails to exec, caught) but wrong for Windows.

**Recommendation:** resolve this once, in `config.py`, via `platformdirs`-style logic
(either take the `platformdirs` dependency — small, pure-stdlib-adjacent, MIT — or hand-roll
~10 lines: `os.environ.get("LOCALAPPDATA")` on `nt`, else `~/.local/state`). Single
recommendation for all three OSes: **`platformdirs.user_state_dir("switchboard")`**, which
already resolves to `~/.local/state/switchboard` on Linux (matches today exactly),
`~/Library/Application Support/switchboard` on macOS (this is a *behavior change* from
today's `~/.local/state/switchboard` on macOS — flag for explicit sign-off, since "no
regression on macOS" is the brief's hard constraint and changing an existing user's state
path silently orphans their old state), and `%LOCALAPPDATA%\switchboard` on Windows. If the
macOS change is unwanted, keep `~/.local/state` literally on POSIX (today's behavior
unchanged) and special-case only `os.name == "nt"` to `%LOCALAPPDATA%` — smaller, zero-risk
diff, and satisfies the "no regression" constraint exactly. This is the safer
recommendation.

### `main_checkout` absolute path recorded in `config.json` — moving-machines note
`store.py:122-132` / `broker.py:1150`: `store.write_config({"main_checkout": str(self.repo)},
...)` writes an absolute path string into `<store>/config.json` at `sb init`, read back by
`main_checkout()` and compared/used throughout (`broker.py:1104`, `:1218`,
`collector.py:568`). This is inherently machine- and OS-specific — a config.json written on
macOS (`/Users/andrew/Code/switchboard`) is meaningless on Windows
(`C:\Users\andrew\Code\switchboard`), and the prior-findings doc already flags this for the
*same-OS* "moving to a new Mac" case. For Windows specifically: `main_checkout()`'s
fallback (`repo_root(cwd).parent` when the recorded path doesn't `.exists()`,
`store.py:130-132`) already self-heals for a fresh `git clone` on a new machine — the
`main_checkout` value from a stale config.json simply fails `Path(recorded).exists()` (a
POSIX path string does not exist as a Windows path either) and falls through correctly. No
fix needed here beyond confirming (not verified live, no Windows box) that
`Path("/Users/andrew/...")` constructed as a `WindowsPath` doesn't raise before `.exists()`
gets to return `False` — it shouldn't (pathlib treats it as a relative-looking weird string,
`.exists()` just returns `False`), but worth a quick unit assertion:
`Path(unix_style_string).exists() is False` under `WindowsPath`.

### `board.py:1684` `_PATHLIKE` regex — silently ignores Windows-style paths (feature loss, not a crash)
`_PATHLIKE = re.compile(r"^(~/|/)?[\w.][\w./-]*\.[a-zA-Z0-9]{1,5}$")` (`board.py:1684`),
used by the backtick-path-extraction feature (`board.py:1723-1759`, opens files an agent
mentioned in chat, e.g. for `cursor`/`code` editor integration) only recognizes `/`-rooted
or `~/`-rooted paths with forward-slash separators. A path an agent or the model emits in
Windows form (`C:\Users\...\foo.py`, or even backslash-relative `switchboard\board.py`)
never matches, so the whole "click through to a mentioned file" convenience quietly does
nothing on Windows — no error, just nothing found. Low severity (cosmetic feature), but
cheap to fix: extend the regex to accept an optional drive letter (`^[A-Za-z]:[\\/]`) and
allow `\` as a separator alongside `/`, or normalize the candidate with
`PureWindowsPath(cand).as_posix()` before matching when `os.name == "nt"`.
`os.path.normpath(root / Path(cand).expanduser())` at `board.py:1741` already uses
`os.path.normpath`, which *is* platform-correct (converts to native separators) — so once a
candidate passes the regex, the join/containment check (`joined.is_relative_to(root)`,
`board.py:1742`) is fine as-is on Windows; the regex is the only gate that needs work.

### Everywhere else path-related — safe as-is (checked and ruled out)
- `stats.py:425-428`, `broker.py:1856`, `sweep.py:114/210`, `broker.py:1817/2913/3529` all
  split/partition on `"/"` — every one of these operates on **git's own output** (`git
  status --porcelain`, branch refs, remote-tracking names), and git always normalizes
  paths and refs to forward slashes regardless of host OS. Confirmed safe; no fix needed.
- `store.py:46-77` (`repo_root`, `worktree_root`) resolve entirely through `git rev-parse
  --git-common-dir` / `--show-toplevel` subprocess calls, then `Path(...)` on git's output.
  Delegating to git this way is exactly right for Windows — git-for-windows normalizes
  drive-letter and backslash paths for you, and `pathlib.Path` parses forward-slash strings
  fine on `WindowsPath`. No fix needed.
- No `os.environ['HOME']` anywhere (grepped) — every home-directory reference goes through
  `Path.home()` or `.expanduser()`, both of which are correctly cross-platform
  (`Path.home()` reads `USERPROFILE` on Windows).
- No raw string path concatenation (`"a" + "/" + "b"`) found; everything uses `Path` /
  `os.path.join` correctly.
- No `/tmp` hardcoding for writable temp state — the one `/tmp` mention
  (`broker.py:560`, `stats.py:587`) is prose/comments about macOS's `/tmp` being a symlink
  to `/private/tmp`, not code.

## 3. STORE location (`.git/agentflow/`)

Confirmed: `store_dir()` = `repo_root(cwd) / _STORE_DIRNAME` (`store.py:80-87`,
`_STORE_DIRNAME = "agentflow"` from `defaults/settings.toml:77`), and `repo_root()` is
git's own `--git-common-dir`, so the STORE's location is entirely git-derived and
OS-agnostic in how it's *found*. The only Windows-relevant risk is the same
`main_checkout` staleness covered above (§2) — confirmed no additional issue specific to
the STORE directory itself; `config.json`'s `main_checkout` is the one absolute-path
assumption in this whole path, and it already self-heals on a fresh checkout.

## 4. Worktree creation (`broker.py`, `herdr.py`)

Worktree creation itself is delegated entirely to the `herdr` CLI (`herdr.py:425-461`,
`create_worktree`/`open_worktree`, both just build an argv list and hand it to
`Herdr._run`/subprocess) — switchboard never computes a `~/.herdr/worktrees/...` path
itself; that's herdr's own concern, and the brief states herdr already has native Windows
support. **No POSIX-only path assumption found in switchboard's worktree-creation code
path** — confirmed by reading `herdr.py:425-461` in full. The one place switchboard *does*
build and interpret a filesystem path around a worktree is `_own_sb_bin`
(`broker.py:400-415`, covered in detail in §5 below, since it's really about `bin/sb`
being runnable, not about worktree creation) and `_worktrees()` (`broker.py:1788-1797`,
which just parses `git worktree list --porcelain` line-by-line splitting on `"worktree "` —
safe, that's a fixed English-language git output prefix, not a path separator).

## 5. Atomic writes & file ops

### `panel.py:250-259` — the one true atomic-write pattern in the codebase — mostly fine on Windows, one real gap
```
tmp = paths.dir / f"snapshot.json.{os.getpid()}.tmp"
fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
...
os.replace(str(tmp), str(paths.snapshot))
```
- `os.replace` on Windows calls `MoveFileExW` with `MOVEFILE_REPLACE_EXISTING`, which
  **does** work atomically onto an existing target — this is exactly why `os.replace` (not
  `os.rename`, which raises on Windows if the target exists) is used here, and it's already
  the right call. Good as-is.
- The remaining Windows risk is the reader side, not this write: `read()` at `panel.py:315`
  does `paths.snapshot.read_bytes()` — a separate open/read/close each tick, so there is a
  narrow window where a reader's handle is open on `paths.snapshot` at the exact instant a
  writer's `os.replace` targets it. CPython's `io`/`os.open` on Windows opens file handles
  with `FILE_SHARE_DELETE` set (this has been true since Python 3.4-ish, specifically so
  that rename-over-open-file works close to POSIX semantics) — so in practice this
  `os.replace` should succeed even mid-read, but this is inference from CPython's known
  Windows file-sharing flags, **not verified on an actual Windows box**, and is worth a
  targeted test/spike before relying on it, since a `PermissionError` here would surface as
  a wedged collector (the "40 readers and a writer" scenario the docstring itself describes
  as "a certainty rather than a risk" under load). No code change recommended unless that
  spike finds a real failure — flagging as unverified rather than assuming it apart from
  the "no fix needed" bucket above.
- `os.open(..., 0o644)` — the mode argument is a POSIX permission bits pattern; on Windows
  `os.open`'s mode parameter only controls the read-only attribute (nonzero-write-bit vs.
  all-zero), so `0o644` is harmlessly ignored/approximated rather than wrong — no fix
  needed, just noting it's inert there.

### `os.access(path, os.X_OK)` — three call sites that will lie on Windows
`board.py:2217`, `collector.py:475`, `broker.py:415` all gate "is this checkout's `bin/sb`
runnable" on `os.access(own, os.X_OK)`. Per CPython's documented Windows behavior,
`os.access(path, os.X_OK)` on Windows **only checks that the path exists** — Windows has no
per-file execute-permission bit for `os.access` to inspect, so this check is a no-op
disguised as a real one on Windows: it will report `bin/sb` (a file with no extension,
containing a `#!/usr/bin/env python3` shebang) as "executable" unconditionally, right up
until something actually tries to run it.

And running it *would* fail on native Windows: `bin/sb` has no extension at all — not even
`.py` — so `subprocess.run([sb, ...])` (`collector.py:2221` uses exactly this pattern; also
implied at `board.py:2217`'s caller and the PATH-priming site below) hits `CreateProcess`
with a filename Windows cannot map to an interpreter (no extension in `PATHEXT`, and Python
shebang lines are not honored by `CreateProcess` — only the `py.exe` launcher parses them,
and only when invoked explicitly as `py <script>`). Expect `OSError [WinError 193]`, or
`FileNotFoundError`. Both call sites already wrap the subprocess call in
`try/except (OSError, subprocess.SubprocessError)` (`collector.py:2223`), so this fails
*safe* (returns `None`, feature silently unavailable) rather than crashing — but the
X_OK check upstream gives false confidence and the two failure modes (link-detection lying,
subprocess failing) compound: on Windows these three call sites will always take the "yes,
runnable" branch and then always fail at actual invocation time, silently disabling: the
doorbell short-circuit (`collector.py:465-477`, `doorbell_sb`), the own-build `inspect`
call (`board.py:2208-2222`, `_inspect`), and the own-checkout PATH-priming pin
(`broker.py:400-415`, `_own_sb_bin`, consumed at `:3341`).

**Recommended fix:** give `bin/sb` (and `bin/sb-stop-hook`, `bin/sb-activity-hook`) a
Windows-runnable form and check for *that* instead of trusting `X_OK`. Two changes needed
together, not just a check fix:
1. Ship a `bin/sb.cmd` (or `bin/sb.ps1`) wrapper alongside the existing POSIX `bin/sb`,
   e.g. `@python "%~dp0sb" %*` — a thin batch shim that calls the shebang-based script via
   an explicit `python`/`py` invocation, so the *same* `bin/sb` Python file stays the
   single source of truth and only a launcher shim differs per OS. This is the standard
   pattern (`pip`, `black`, and most Python console-script installers ship exactly this
   `name` + `name.cmd`/`name.ps1` pair on Windows).
2. Replace the `os.access(..., os.X_OK)` checks with an OS-aware "does a runnable entry
   point exist" check: on POSIX, keep `X_OK` (unchanged, zero regression); on `nt`, check
   for `bin/sb.cmd` (or `.exe` if ever compiled) next to `bin/sb`, and invoke *that* path in
   the subsequent `subprocess.run` calls instead of the extensionless `bin/sb`.

Same fix applies to the hook scripts below (§5, hooks), which have the identical
extensionless-shebang problem plus a shell-quoting problem on top.

### `hooks.py:113,126,143` + `bin/sb-stop-hook`, `bin/sb-activity-hook` — will not fire on native Windows
`_entry_point()` (`hooks.py:81-88`) returns the absolute path to `bin/sb-stop-hook` /
`bin/sb-activity-hook` — both extensionless files with a `#!/usr/bin/env python3` shebang
(`bin/sb-stop-hook:1`, `bin/sb-activity-hook:1`), same category as `bin/sb` above. These
paths are wrapped with **`shlex.quote`** (`hooks.py:113,126,143`) and embedded directly as
the `command` string in a Claude Code hook settings JSON (`hooks.py:114-153`). Two
independent problems:
1. **Extensionless shebang script**, same as `bin/sb` — Claude Code's hook runner passes
   `command` to a shell (on native Windows, `cmd.exe` by default per Claude Code's own
   docs, unless the user has Git Bash configured) — `cmd.exe` cannot execute an
   extensionless file with no `PATHEXT` match and does not honor `#!` shebang lines at all.
2. **`shlex.quote` produces POSIX quoting** — single-quotes a path containing spaces or
   special characters (`shlex.quote` is documented as POSIX-shell-specific). `cmd.exe` does
   not treat single quotes as quoting at all (they'd be passed through as literal
   characters, splitting the path or being interpreted as part of the filename), so any
   install path containing a space (extremely common on Windows — `C:\Program Files\...`
   or even a spaced project folder name) breaks the quoting itself, independent of the
   extension problem.

**Recommended fix**, no POSIX regression (both changes are additive, `os.name == "nt"`
branches):
1. Ship `bin/sb-stop-hook.cmd` / `bin/sb-activity-hook.cmd` shims (same pattern as `bin/sb`
   above), and have `_entry_point()` return the `.cmd` path on `nt`, the current
   extensionless path unchanged on POSIX.
2. Quote with a Windows-appropriate quoting function on `nt` (double-quote the argument,
   escape embedded `"` per `cmd.exe`'s rules — `shlex` has no Windows equivalent, but
   `subprocess.list2cmdline([arg])` produces correct Windows argv-quoting and is stdlib) —
   keep `shlex.quote` for POSIX, branch on `os.name`.

**Test implications:** both of these can be pinned without a Windows box — a test that
monkeypatches `os.name = "nt"` and asserts `_entry_point()` returns a `.cmd` path, and a
separate string-level test asserting the built `command` string uses
`subprocess.list2cmdline`-style quoting when `nt`. The actual "does `cmd.exe` execute this"
question needs either a Windows CI runner or manual verification — cannot be pinned in a
POSIX-only test suite.

### PATH-priming pane command — POSIX-shell-only, not fixable by a path-handling change alone
`broker.py:3341-3348` (`_own_sb_bin` consumer, part of the "pin the pane to this checkout's
`bin/`" mechanism, see `broker.py:3295-3348` docstring) types
`export PATH=<dir>:"$PATH"; echo "sb=$(command -v sb)"` directly into the herdr pane's
shell. `export`, the `:`-separated `PATH` (Windows uses `;`), and `$(...)` command
substitution are all POSIX-shell syntax; a native Windows pane running `cmd.exe` or
PowerShell as its default shell would receive this as literal garbage (`cmd.exe`: `export`
is not a command; PowerShell: `export` is not a cmdlet, `$(...)` *is* valid PowerShell
syntax but means something different, `:"$PATH"` is nonsense either way). This is squarely
a path-handling concern (it exists to fix `PATH`) but the actual defect is shell dialect,
not path syntax — flagging here since it lives in the same code region as the `bin/sb`
X_OK issue and shares the same root cause (`bin/sb` being POSIX-only), but the fix belongs
with whichever concern is auditing subprocess/shell invocation, since it needs a
`shell=cmd.exe` / `shell=powershell` branch, not just a path fix. **Spotted, not chased —
see "spotted elsewhere" below.**

### Everywhere else atomic-write/file-op related — safe as-is (checked and ruled out)
- `herdr.py:166` — `prompt_file_path(name, cwd).unlink(missing_ok=True)` — plain delete,
  `missing_ok=True` is portable, no atomicity claim made, no issue.
- No other `tempfile`, `NamedTemporaryFile`, or `mkstemp` usage anywhere in `switchboard/`
  — `panel.py`'s hand-rolled `os.open(..., O_CREAT|O_TRUNC)` + `os.replace` (above) is the
  only temp-file pattern in the codebase; confirmed no second site needs review.
- No `os.rename` anywhere (only `os.replace`, which is the correct, Windows-safe choice) —
  confirmed by grep.
- `panel.py:433/470/474` and `sweep.py:308`, `plugins.py:687`, `broker.py:2863` all use
  `fcntl.flock` for locking — **out of this concern's scope** (the brief's atomic-write
  section is about `os.replace`/`tempfile`/`chmod`/`X_OK`, not locking primitives) and
  already flagged by the prior-findings doc and presumably another researcher's concern
  (the `fcntl`/`termios` import-time crash). Not re-audited here beyond confirming these are
  locking, not path/atomic-write, concerns.

## Spotted elsewhere (not chased — outside this concern)

- `broker.py:3341-3348` — POSIX-shell (`export`, `$(...)`, `:`-separated PATH) typed
  directly into a pane's shell to prime `PATH`. Root cause is the same `bin/sb`
  POSIX-shebang problem covered in §5, but the actual fix needs a shell-dialect branch
  (subprocess/pane-invocation concern, not path handling per se).
- `fcntl`/`termios` module-level imports (`broker.py:33`, `plugins.py:62`, `panel.py:69`,
  `sweep.py:44`, `board.py:55`) and the `flock`/`tcgetattr`/`tcsetattr` call sites — hard
  import-time crash on Windows, already documented in `_prior-findings.md` and out of this
  concern's scope (locking/terminal, not filesystem paths).
- `live.py` (`lsof`), `stats.py`/`broker.py` (`ps -Ao`, `vm_stat`) — POSIX-only subprocess
  tools, already documented in `_prior-findings.md`, out of scope (subprocess/process
  concern, not filesystem).
- No DESIGN-TRUTH.md mentions of Windows/POSIX/cross-platform anywhere (grepped, zero
  hits) — whoever owns the eventual plan will be writing this policy from scratch, not
  reconciling it against existing doc language.

## Summary table (this concern only)

| file:line | issue | breaks on Windows how | also broken on Linux? | fix risk to POSIX |
| --- | --- | --- | --- | --- |
| `broker.py:1116` | `symlink_to` no `target_is_directory`, no capability fallback | wrong link type + needs privilege; silent `link_config` failure loses `CLAUDE.md`/`.switchboard` | no | none if branched on `os.name`/capability probe |
| `broker.py:1113`, `:1856` | `is_symlink()` used as the sole "is this ours" check | under-detects if a copy/junction fallback is added | no | must update in lockstep with the fix above |
| `defaults/settings.toml:66` (`plugins.py:608`) | `~/.local/state/switchboard` hardcoded | works but wrong convention (`%LOCALAPPDATA%`) | no | none, additive `nt` branch |
| `board.py:1684` `_PATHLIKE` | regex rejects backslash/drive-letter paths | feature silently no-ops on Windows-style paths | no | none, regex widening only |
| `board.py:2217`, `collector.py:475`, `broker.py:415` | `os.access(path, os.X_OK)` | always "yes" on Windows, then the subprocess call fails anyway | no | none, needs `bin/sb.cmd` shim + OS-aware check |
| `hooks.py:113/126/143` + `bin/sb-stop-hook`/`sb-activity-hook` | extensionless shebang script, POSIX `shlex.quote` | hook never fires on native Windows; breaks harder with spaces in the path | no | none, needs `.cmd` shims + `list2cmdline` on `nt` |
| `panel.py:250-259` | `os.replace` atomic swap | works, but reader-side share-mode behavior unverified live | no (POSIX semantics already correct) | none — verify only, no code change proposed |

Everything else grepped for this concern (`os.rename`, `tempfile`, `chmod`,
`main_checkout` staleness, `repo_root`/`worktree_root`, herdr worktree creation itself,
`.switchboard/briefs`+`notes` creation) checked out clean or self-heals already — see
inline "safe as-is" notes above for what was ruled out and why.
