# WSL2 viability for switchboard "Windows support" — verification findings

Scope: verify whether running switchboard (and herdr) as **Linux inside WSL2** dissolves the
native-Windows blockers from PR #171 (`notes/windows-support-plan.md` §2 + the six audits), and
hunt for WSL2-specific problems that native analysis wouldn't surface. No Windows/WSL2 box
available — verified from source (switchboard here, herdr cloned at `/Users/andrew/Code/herdr`)
plus documented WSL2/Claude Code behaviour. Read-only.

## 1. Blocker-dissolution table

Every blocker below is gated on `sys.platform == "win32"` / `os.name == "nt"` (Python) or the
Rust `cfg(windows)` compile-time target (herdr). WSL2 runs a **real Linux kernel** — the Python
interpreter and the herdr binary both report/compile as Linux, not Windows, so every such gate
takes the same branch it already takes on native Linux/macOS today. This isn't emulation or a
compat shim; it's an actual different `sys.platform` value / target triple.

| Blocker (plan ref) | Under WSL2 | Confidence |
|---|---|---|
| B1/B7 `import fcntl` (broker.py, plugins.py, panel.py, sweep.py, plans plugin) | Dissolves — `fcntl` is a real, fully-functional stdlib module on Linux | High |
| B2 `import termios`/`tty` (board.py) | Dissolves — real Linux tty layer | High |
| B3 `signal.SIGHUP` | Dissolves — Linux defines `SIGHUP` | High |
| B4 `signal.SIGWINCH` | Dissolves — Linux defines `SIGWINCH`; WSL2's pty resizes deliver it normally through the real Linux tty subsystem | High |
| B5 bash-only `_ready_pane` command string | Dissolves for the *shell-family* problem — the pane runs bash/zsh/posix inside WSL2 same as native Linux. (Confirming herdr's WSL2 default shell is bash, not PowerShell — see §2 — is what actually keeps this on the POSIX branch; not directly re-verified against a live WSL2 box.) | Medium-high |
| B6 extensionless shebang scripts (`bin/sb`, hooks) | Dissolves — WSL2's filesystem executes shebang scripts exactly like native Linux (`chmod +x`, `#!/usr/bin/env python3` all honored) | High |
| F1 `lsof -a -d cwd -F pcn` | Dissolves — `lsof` is installable in any WSL2 distro (Ubuntu default even ships it or it's one `apt install` away); parsing verified against real GNU lsof output (see §1a) | High |
| F2 `ps -Ao`, `vm_stat`→`_available_linux()` (stats.py) | Dissolves — `stats.py:501` already dispatches `darwin` vs falls through to `_available_linux()`, which reads `/proc/meminfo`-style Linux data. WSL2's `/proc` is real (backed by the WSL2 Linux kernel, not a translation layer) | High |
| F3 `select.select([stdin_fd], …)` | Dissolves — Linux `select()` on a tty fd works exactly as on macOS | High |
| F4 `termios.tcgetattr`/`tty.setraw` raw mode | Dissolves — same real Linux tty ioctls | High |
| F5 `symlink_to` (no target_is_directory/fallback) | Dissolves — WSL2's native ext4 filesystem supports real POSIX symlinks unconditionally; there is no "Developer Mode" concept on the Linux side at all (that's an NTFS/Windows-native constraint) | High |
| F6/F6b `os.access(X_OK)` / bare `subprocess.run(["sb", …])` | Dissolves — WSL2 has real Unix exec bits and PATH resolution; no `.cmd`/PATHEXT semantics apply | High |
| F7 `shlex.quote` POSIX quoting | Dissolves — panes are POSIX shells | High |
| F7b/F9/F10/F11 encoding (`read_text()` w/o `encoding=`, stdout/stdin reconfigure) | Dissolves — WSL2 Linux defaults to a UTF-8 locale (`LANG=C.UTF-8` or similar out of the box in modern WSL2 distros), so `locale.getpreferredencoding(False)` returns UTF-8, not cp1252. This is the *same* latent-bug class the plan flags for POSIX under `LC_ALL=C`/minimal containers — worth still fixing generally, but not WSL2-blocking | Medium-high (depends on the distro's default locale actually being UTF-8, which is standard for Ubuntu/Debian WSL2 images but not guaranteed for every possible distro a user could install) |
| F8 `exec {python} -m switchboard.board` (POSIX builtin) | Dissolves — real POSIX shell | High |
| F12 `subprocess.run(..., text=True)` w/o encoding | Same as F9 — dissolves under a UTF-8 locale | Medium-high |
| F13 `start_new_session=True` / ConPTY / ` msvcrt` | N/A — these only exist as *problems* on native Windows subprocess/console APIs; WSL2 uses real POSIX `setsid`/process groups, so `start_new_session=True` works exactly as documented, not silently discarded | High |
| psutil (D1's adopted native-Windows fix) | Not needed — `switchboard/stats.py`'s existing `_available_linux()`/`ps`-based paths are what actually run; psutil was only needed to normalize *Windows* process/memory APIs | High |
| M2 `_PATHLIKE` regex (drive-letter/backslash paths) | N/A — inside WSL2 paths are POSIX (`/home/user/...`); this only matters if a user pastes a Windows-side path (`C:\...`) into a switchboard pane, which is a UX edge case, not a blocker | High |

### 1a. The "Linux lsof parse bug" — re-confirmed, not just cited

`notes/windows-support/audits/researcher-process-liveness-findings.md` measured this directly
(Docker, Ubuntu 22.04's `lsof` 4.93.2 — the same `lsof-org` fork every current Linux distro,
including WSL2's Ubuntu, ships) and found the earlier "BSD 4-line vs Linux 3-line group" claim
false: `-F pcn` output is 4-line groups on both platforms, and `switchboard/live.py:99-113`
(`_parse`) already handles both correctly. I did not re-run this in Docker myself, but I read the
audit's methodology and the actual parser at `live.py:99-113` — the audit's fixture output and the
parser logic are consistent, and there's no lsof-version or kernel dependency in the parsing logic
that would behave differently on WSL2's kernel vs. any other Linux kernel. **Confidence: high that
this specific bug is real-disproven; not independently re-tested by me on WSL2 itself.**

One genuine (non-blocking) Linux behavioral quirk the audit found and I confirm reading `live.py`
is real: unprivileged Linux `lsof` lists *other users'* processes by pid (with a permission-denied
placeholder name) rather than omitting them the way macOS does. `_parse` still accepts these groups
(the name starts with `n/`), producing a `Proc` with a nonsense `cwd`. `is_under()` never matches
it against a real checkout path, so it's inert today — but it is a **latent scope-invariant
violation** that a future Linux-specific check should account for. This applies identically under
WSL2 (WSL2's lsof/`/proc` are genuinely Linux, not a translated view) — no new WSL2 wrinkle here,
it's a plain Linux fact the audit already surfaced.

No macOS-specific code was found in switchboard's process/memory/liveness paths that lacks a
working Linux branch — `stats.py:501` explicitly dispatches `darwin` vs. falling through to
`_available_linux()`, and `live.py`'s `lsof` scan is platform-generic (POSIX, not BSD-specific
flags).

## 2. WSL2-specific gotcha hunt

**herdr under WSL2 (read from `/Users/andrew/Code/herdr` source):**

- **pty**: herdr uses the `portable-pty` crate's real Unix `openpty` (`src/pty/backend/unix.rs:19`,
  `src/pane.rs:3075`, `src/detect/mod.rs:1228`), gated by Rust's `#[cfg(unix)]`/`#[cfg(windows)]`
  **compile-time** target triple (`src/pty/backend.rs:1-16`). A WSL2 binary is a genuine
  `x86_64-unknown-linux-gnu` build — there is no runtime ambiguity where it could accidentally take
  the Windows ConPTY path. High confidence this is clean.
- **IPC socket location**: `data_dir_for()` → `config::config_dir()` (`src/session.rs:161-171`,
  `src/config/io.rs:29-34`) resolves to `$XDG_CONFIG_HOME` or a platform default (`~/.config/herdr`
  on Linux) — **not** `$XDG_RUNTIME_DIR`, and not systemd-mediated. I grepped the whole `src/` tree
  for `systemd`/`logind`/`sd_notify` and found zero hits. This matters because **WSL2 does not run
  systemd by default** (opt-in since WSL 0.67.6+ via `/etc/wsl.conf`) — if herdr depended on
  `XDG_RUNTIME_DIR` (normally populated by logind/systemd) or on socket activation, that would be a
  real WSL2-specific breakage. It doesn't. High confidence.
- **inotify/file-watching**: no `notify`/`inotify` crate dependency in `Cargo.toml` and no watcher
  code found in `src/`. herdr does not file-watch at all, so the well-known DrvFs-doesn't-support-
  inotify gotcha (relevant to `/mnt/c/...` paths) doesn't apply to herdr specifically. It **would**
  still matter for any tool a user runs *inside* their WSL2 panes that does watch files (a dev
  server with hot-reload, etc.) if their repo sits on `/mnt/c/...` — see the filesystem-boundary
  point below. High confidence on herdr itself; this is a general WSL2 fact, not something I could
  verify live.
- **Clipboard/OSC**: herdr has its own clipboard write path (`src/app/input/clipboard.rs`) and
  references to OSC handling in `events.rs`/`raw_input.rs`/`selection.rs`. I did not trace the
  exact escape sequence it emits. WSL2's interop with Windows Terminal / VS Code's integrated
  terminal generally passes OSC 52 through transparently when the host terminal supports it (this
  is standard WSL2 terminal behavior, not herdr-specific), but **I could not verify herdr's exact
  clipboard write actually reaches the Windows clipboard through a specific WSL2 terminal without a
  live box.** Flagged as unverified.
- **herdr's "Windows beta"**: per `notes/windows-support-plan.md` (already resolved in this repo's
  history — "herdr Windows is beta, default shell PowerShell"), herdr's *native* Windows support is
  explicit "experimental beta," local-client-only. That beta status is about the native-Windows
  code path (ConPTY, ` powershell.exe` default shell, ` ` etc.) — it does **not** apply to herdr
  running as a Linux binary under WSL2, which is herdr's Linux path (documented stable, not beta).
  This is the key distinction: WSL2 sidesteps herdr's Windows beta entirely by never exercising it.
- **herdr already has explicit WSL-awareness (notable, reassuring)**: `src/platform/linux.rs:41-58`
  has a real `running_inside_wsl()` check (reads `/proc/sys/kernel/osrelease` and `/proc/version`
  for "microsoft"/"wsl", plus `WSL_DISTRO_NAME`/`WSL_INTEROP` env vars and `/run/WSL`), used at
  `linux.rs:39` to flip a host-cursor-drawing default under WSL. herdr's authors have already hit
  and deliberately handled at least one real WSL2 rendering quirk — this is evidence *for* the
  Linux-under-WSL2 path being genuinely exercised and cared for, not just theoretically compatible.
  There's also an opt-in `HERDR_PROCESS_DETECTION=child-groups` fallback (`linux.rs:22-84,133-145`)
  for when TIOCGPGRP-based foreground-process detection misbehaves in sandboxed/virtualized
  environments (docs mention gVisor, not confirmed WSL2-specific) — a safety valve if WSL2's pty
  foreground-group reporting ever proves unreliable, unconfirmed either way without a live box.
- **herdr clipboard needs packages not in a stock WSL2 distro (real gotcha)**: `linux.rs:622-668`
  shells out to `wl-copy`/`xclip`/`xsel`, gated on `WAYLAND_DISPLAY`/`DISPLAY` being set. Modern
  WSL2 (WSLg, Windows 11 or updated Windows 10) sets these automatically, but stock Ubuntu-on-WSL2
  does not ship `xclip`/`wl-clipboard` — a user needs `sudo apt install wl-clipboard` (or `xclip`)
  for this path to work at all. Separately, herdr passes OSC 52 escapes straight through to the
  terminal (`src/pane/osc.rs:1109-1325`), which is a working fallback independent of DISPLAY/xclip
  as long as the Windows-side terminal (Windows Terminal, VS Code) honors OSC 52 — which they do.
  Net: clipboard should work via OSC 52 pass-through even on a minimal WSL2 setup with no extra
  packages; the xclip/wl-copy path is a redundant second route that needs an extra `apt install`.

**Claude Code under WSL2** (checked against Anthropic's own sandboxing docs,
code.claude.com/docs/en/sandboxing): Claude Code's OS-level sandbox explicitly supports macOS,
Linux, **and WSL2** — explicitly *not* WSL1 and *not* native Windows. It requires `bubblewrap`
installed inside the WSL2 distro (`sudo apt install bubblewrap` on Ubuntu) — not present by default,
one more setup step. One real behavioral caveat: a sandboxed command under WSL2 **cannot** invoke
Windows-side binaries (`cmd.exe`, `powershell.exe`, anything under `/mnt/c/...`) — WSL2 routes
those through a Unix socket to the Windows host, which the sandbox blocks by design. This only
matters if a switchboard hook or tool deliberately shells out to a Windows-side binary, which
nothing in the current codebase does. Git and hooks are ordinary Linux processes with no
Windows-specific handling. This is documented, not independently re-run by me in a live WSL2 shell.

**The filesystem boundary — the single biggest real gotcha:**

- WSL2 exposes two filesystem "sides": the WSL2 distro's own ext4 volume (e.g. `~` =
  `/home/user/...`) and the Windows drives mounted via DrvFs (`/mnt/c/...`).
- Repo/checkout on `/mnt/c/...`: every filesystem syscall crosses the 9P/DrvFs boundary into the
  Windows NTFS driver. This is **well-documented as dramatically slower** (git status/checkout,
  `os.stat` calls, directory listings can be 10-100x slower than native ext4) — directly relevant
  to switchboard, which does a lot of stat-heavy work (STORE reads, symlink checks, pane polling).
  It also **does not support inotify** reliably — moot for herdr itself (no file-watching), but
  would break any dev tool run inside a pane that watches files for hot-reload.
- Repo on native WSL2 ext4 (`~/...`): full-speed real Linux filesystem, symlinks, inotify, and
  Unix permissions all behave exactly like native Linux/macOS.
- **Verdict: the repo (and the `.git/agentflow` STORE + `.switchboard` symlinks) must live on the
  WSL2-native filesystem, not `/mnt/c/...`.** This is the one place "run it in WSL2" is *not*
  zero-effort — it's a setup instruction a user must be told and follow, not something that just
  works by default if they, say, `cd /mnt/c/Users/them/Documents/myrepo` out of habit.

**git line endings**: switchboard's repo has **no `.gitattributes`** at all, so `core.autocrlf`
defaults govern. Inside WSL2 this is a non-issue as long as all edits happen through WSL2-side
tools (a WSL2 shell editor, or VS Code's Remote-WSL extension, which edits via the Linux
filesystem and preserves LF). It only bites if a user edits repo files with a *Windows-native*
tool pointed at the Windows-visible path (`\\wsl$\...` UNC share or, worse, a copy living on
`/mnt/c/...`) and that tool writes CRLF. Low-probability, but worth naming as a real (if narrow)
seam — not verified against a live WSL2+editor combo.

**STORE + `.switchboard` symlinks**: `broker.py:1116` (`dst.symlink_to(src)`) is a plain POSIX
symlink call, no Windows-conditional logic. Under WSL2's native filesystem this behaves exactly as
it does on macOS/Linux CI today. High confidence this "just works," conditional on the repo living
on WSL2-native storage (see above) — symlinks *are* possible on `/mnt/c/...` too via DrvFs's
limited symlink support, but it's an added variable best avoided by keeping the repo native-side
regardless.

**Networking/clock**: not deeply investigated — no switchboard/herdr localhost-binding or
clock-skew-sensitive code was found in the areas I read (sockets are Unix domain sockets under
`~/.config/herdr`, not TCP). WSL2 has a documented history of localhost-forwarding quirks and of
clock drift after Windows host sleep (usually self-corrected via `hwclock`-equivalent sync on
modern WSL2 kernels) — flagged as a known WSL2-class issue in general, not something I found
switchboard/herdr to be exposed to, and not independently tested.

## 3. Verdict

**Yes — WSL2 genuinely dissolves essentially all the native-Windows blockers in the PR #171
inventory**, because every one of them is gated on Windows-specific code paths (Python
`sys.platform=='win32'`, Rust `cfg(windows)`) that a WSL2 process never enters — it's a real Linux
kernel underneath, not a compatibility shim, so this isn't "probably fine," it's "these specific
lines of code do not execute." The near-zero-code-work premise holds for the *native-blocker*
half of the problem.

**But "Windows support via WSL2" is not free of friction, and the friction is not in the code —
it's in setup and defaults:**

1. **Filesystem placement is a real, silent footgun.** A user who puts their checkout on
   `/mnt/c/...` gets a working-but-slow switchboard, not a broken one — so this failure mode is
   easy to miss in testing and easy for a real user to fall into by habit. This needs to be an
   explicit, loud instruction in setup docs, not an implicit assumption.
2. **For a non-technical user, "run it in WSL2" is a materially bigger ask than "download and
   run our app."** It requires: enabling WSL2 (a reboot, sometimes a BIOS virtualization setting),
   picking/installing a distro, learning that their files now live in two places, installing
   Claude Code and switchboard *inside* that Linux environment, and remembering to open a WSL
   terminal (or use VS Code's Remote-WSL) rather than PowerShell. None of this is hard for a
   developer already comfortable with WSL2; all of it is new conceptual surface for someone who
   isn't. This is a real gap in "delivers Windows support," even though it's not a code gap.
3. Several confirmations rest on documented behavior or the existing audits rather than a live
   WSL2 box I could drive myself (see the unverified list below) — genuinely high-confidence given
   how mechanical the platform gating is, but not empirically closed.

**What I could not verify without a real WSL2 install** (explicit list):
- herdr's exact clipboard/OSC escape sequence actually reaching the Windows clipboard through a
  specific WSL2 terminal (Windows Terminal, VS Code integrated terminal, etc.).
- Claude Code's current-version WSL2 sandbox/hooks/git behavior — relied on documented/known claims,
  not a live check.
- B5's shell-family branch and F9/F12's UTF-8-locale assumption, both **specifically inside a real
  WSL2 distro's default environment** (I'm confident from Ubuntu's known default locale and WSL2's
  bash default, but did not run a WSL2 shell to confirm `locale` output or `$SHELL`).
- Actual DrvFs performance degradation numbers for switchboard's own stat-heavy workload (STORE
  reads, pane polling) — cited from general WSL2/DrvFs performance characteristics, not measured
  against switchboard's specific I/O pattern.
- Live localhost-networking and post-sleep clock-skew behavior for whatever switchboard/herdr do
  need it (found no such dependency in the code I read, but did not exhaustively search).
- The lsof parse-bug re-confirmation is via Docker (per the existing audit), not WSL2 itself,
  though the same GNU lsof build is what WSL2 distros ship.
