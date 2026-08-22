# Running switchboard on a Windows PC — the plan

Investigation only, 2026-08-22. No production code changed. **The ask was "gain Windows
support."** This document answers that ask the cheapest correct way, after correcting an earlier
scope error (see the note below).

## TL;DR

**Recommendation: run switchboard inside WSL2** (Windows Subsystem for Linux 2 — a real Linux
kernel Microsoft ships built into Windows). WSL2 *is* Linux, so every one of the ~30
*Windows-gated* blockers the native port would have to fix simply never executes, and it rides
herdr's **stable** Linux support instead of herdr's experimental-beta *native*-Windows support.

The code cost is **one required fix, not zero** — `live.py`'s `lsof` invocation is measurably
blind on Ubuntu 24.04, the distro `wsl --install` gives you, which makes `sb cleanup` and
`sb workspace close` refuse permanently. It is a one-character fix (§2.1) and it is the only thing
standing between "runs on WSL2" and "works on WSL2". Beyond that the cost is setup friction and
one placement rule (keep the repo on the Linux side, not `/mnt/c`).

Two honesty notes up front: switchboard's Linux CI runs the unit suite with **no herdr and no
tmux**, so the pane/agent/fleet surface is unproven on Linux (`tests.yml:17-21`) — "CI-tested on
Linux" would be an overclaim. And the encoding-hygiene class is gated on the runtime *locale*, not
on Windows, so it does not dissolve by moving platforms; WSL2 just happens to default to UTF-8.

A full **native-Windows port** was investigated first and is a large, unbuilt effort on top of a
beta foundation. It is retained as a fallback only (`windows-support/native-port-plan.md`).

---

## 0. Scope correction (why this supersedes the native-port plan)

The first pass built a comprehensive plan to make switchboard run as a **native Windows program**
(PR #171's original content, now `windows-support/native-port-plan.md`). That was a mistake in
framing: the user asked to "add Windows support … gain Windows support" — the word "native" was
introduced by the planning lead and never in the ask. The prior migration investigation the lead
was handed had *already* identified WSL2 as the cheap path and called native "a genuine port," but
that was not surfaced. This redo corrects that: it evaluates the actual question — "how does the
user get switchboard working on their Windows PC?" — for which WSL2 is the answer. (Root cause
filed as a switchboard bug.)

---

## 1. Why WSL2 works — every *Windows-gated* blocker dissolves

The native-port plan found ~30 platform-specific blockers. **Every blocker that is gated on a
Windows-specific code path** — Python `sys.platform == "win32"` / `os.name == "nt"`, or herdr's
Rust `cfg(windows)` compile-time target. A process inside WSL2 runs on a **real Linux kernel**;
the Python interpreter reports `linux` and the herdr binary is a genuine
`x86_64-unknown-linux-gnu` build. So none of those Windows branches ever execute — this is not
emulation or a shim, these specific lines of code simply do not run. (Full verification, blocker
by blocker, in `windows-support/researcher-wsl2-viability-findings.md`.)

**Two classes are not Windows-gated and therefore do not dissolve**, and the table below carries
both rather than omitting them:

- **F1, the `lsof` scan** — gated on the *lsof revision the distro ships*. Measured broken on the
  default WSL2 distro. This is a required code fix; see §2.1.
- **The ~52 encoding sites (F7b/F9/F10/F11/F12)** — gated on the *runtime locale*. Nothing about
  them is a Windows branch; they are a latent POSIX bug today. WSL2 does not fix them, it merely
  defaults to UTF-8 so they do not bite. See §2.5.

A third caveat sits under the whole table: **WSL2 moves the user from macOS to Linux, not to "the
tested platform."** `.github/workflows/tests.yml:17-21` states that the Linux CI leg has no herdr
and no tmux, so *"nothing here exercises a real pane, a real agent or a real fleet"*, and names the
macOS leg as the one where nothing skips. Linux CI green is the unit suite, not the fleet. The
confidence column below is about platform-gating mechanics; it is not evidence that switchboard's
Linux leg has been exercised in anger.

| Native blocker (native-plan ref) | Under WSL2 | Confidence |
|---|---|---|
| `import fcntl` (broker/plugins/panel/sweep/plans) — B1/B7 | Real Linux stdlib module | High |
| `import termios`/`tty`, raw-mode input, `select` on stdin — B2/F3/F4 | Real Linux tty layer | High |
| `signal.SIGHUP` / `SIGWINCH` — B3/B4 | Both defined on Linux; WSL2 pty delivers `SIGWINCH` on resize | High |
| **`lsof` — F1** | **Does NOT dissolve.** lsof 4.95.0 (Ubuntu 24.04, Debian 12) emits **3-line** `-F pcn` groups; `live._parse` rejects the whole scan, `scan()` returns `None`, and `broker.py:2299-2311` refuses every `sb cleanup`/`workspace close` **permanently**. Measured, unprivileged, in Docker — `windows-support/lsof-linux-measurement.md`. One-character fix in §2.1 | **Measured broken** |
| `ps -Ao` / `vm_stat` — F2 | `stats.py:501` dispatches darwin→`_available_darwin()`, else `_available_linux()` reading real `/proc/meminfo`; `_PS` uses portable `-o` forms | High |
| encoding class — F7b/F9/F10/F11/F12 (~52 sites) | **Not Windows-gated — locale-gated.** Does not dissolve; WSL2's UTF-8 default means it does not bite. Latent POSIX bug regardless (§2.5) | Medium (rests on the distro locale, not on code paths) |
| symlinks needing Developer Mode — F5 | Native POSIX symlinks; no "Developer Mode" concept on the Linux side | High |
| `.cmd`/shebang/`os.access(X_OK)`, `shlex.quote`, bash-only `_ready_pane`, `exec` — B5/B6/F6/F7/F8 | Panes are POSIX shells running shebang scripts with real exec bits | High |
| ConPTY / `msvcrt` / `start_new_session` discarded — F13 | N/A — these are *native-Windows* API problems; WSL2 uses real POSIX `setsid`/pty | High |
| `psutil` adoption (native fix D1) | Not needed — the existing Linux `ps`/`/proc` paths run | High |

**herdr's server layer under WSL2 is genuinely Linux** — the layer switchboard drives (verified
from source at `/Users/andrew/Code/herdr`, HEAD `69a07fd`): the pty is the `portable-pty` crate's
real Unix `openpty` behind a compile-time `cfg(unix)` gate (`src/pty/backend.rs:1-5`,
`backend/unix.rs:12-24`); the IPC socket lives under `~/.config/herdr` with **no systemd /
`XDG_RUNTIME_DIR` dependency** — herdr *pins* this with a test
(`src/api/server.rs:929`, `socket_path_defaults_to_config_dir_even_when_xdg_runtime_dir_is_set`),
which matters because WSL2 doesn't run systemd by default; the server daemonises with real POSIX
`setsid` (`src/platform/mod.rs:73-85`); and there is **no** inotify file-watching. herdr's Windows
*beta* status is about its native-Windows (ConPTY/PowerShell) code path, which a Linux binary
cannot execute.

**But "WSL2 is just Linux" is not true of herdr as a whole, and the plan should not say it is.**
herdr detects WSL **at runtime, from a Linux binary**, and diverges in three places — all in the
interactive client, none in the pty/server/IPC layer switchboard uses:

- **Drawn cursor.** `src/platform/linux.rs:38-50` — `should_draw_host_cursor_by_default()` returns
  `running_inside_wsl()`, so herdr draws its own cursor rather than the terminal's, the same
  workaround it applies to native Windows. **Consequence for the human at the keyboard:** a drawn
  cursor is not the anchor Windows uses for CJK IME composition, so IME candidate UI can land in
  the wrong place. Fix: `[ui] host_cursor = "native"`. herdr's own docs put this caveat on the
  *Windows beta* page and say "native Windows **and WSL**".
- **Clipboard route.** `src/selection.rs:277-320` — `is_wsl()` forces clipboard writes down OSC 52
  rather than native clipboard tools. Deliberate, and it is what populates Windows Terminal's
  clipboard history.
- **Graphics cell size.** Under WSL the pty's `TIOCGWINSZ` pixel fields come back zero, so herdr
  queries the host for cell size instead of guessing 8x16 — a measured WSL-specific ioctl gap.

These are evidence WSL is a *cared-for, exercised* herdr target, not an untested one. But cared-for
is not identical, and one WSL2-specific degradation **does** reach switchboard — see §2.3.

**Claude Code under WSL2** is a documented/supported way to run on Windows, and its sandbox works
under WSL2 (but **not** native Windows) — another point in WSL2's favor.

---

## 2. The real costs — one code fix, one correctness rule, and setup friction

WSL2 is near-zero *code* work. It is not zero code work, and it is not zero friction.

### 2.1 One required code fix: the `lsof` scan is blind on the default WSL2 distro

`live.py:61` runs `lsof -a -d cwd -F pcn`. At lsof **4.94+** the `f` field is only emitted when
`-F` asks for it, and `-F pcn` does not ask. So on **Ubuntu 24.04** — the distro `wsl --install`
installs by default — and on Debian 12, groups come back **3 lines** instead of 4, `_parse`
(`live.py:100-113`) rejects the entire scan, `scan()` returns `None`, and `broker.py:2299-2311`
raises *"cannot close …: this machine could not be asked what is running in …"*. `sb cleanup` and
`sb workspace close` are **dead**, permanently, by design — the gate treats unknown as not-empty.

Measured in Docker, unprivileged, across five images (`windows-support/lsof-linux-measurement.md`):
Ubuntu 22.04 / Debian 11 (lsof 4.93.2) and macOS (4.91) give 4-line groups; Ubuntu 24.04 /
Debian 12 (4.95.0) give 3. Exit code is 0 in every case, so `live.py:94` is not the hazard — the
shape check is.

**The fix is one character:** `CWD_SCAN = ("lsof", "-a", "-d", "cwd", "-F", "pcnf")`. Verified to
produce the 4-line `p`/`c`/`fcwd`/`n` group `_parse` already expects on all five images, macOS
included — so it is not a Linux special-case, it is the invocation being explicit about a field it
was relying on lsof to volunteer.

This also settles a tracked contradiction: `tests/test_live.py:70`'s darwin-only skip and the CI
comment at `tests.yml:17-21` are **correct**, and `audits/researcher-process-liveness-findings.md`'s
headline claim that the Linux parse bug "does not reproduce" is **wrong** — it tested only lsof
4.93.2. Its recommendation to un-skip that test would have turned a real gap into a red build.

*(Second, smaller Linux difference from the same measurement: unprivileged Linux lsof lists foreign
processes as `n/proc/<pid>/cwd (readlink: Permission denied)` rather than omitting them the way
macOS does. It parses fine and never matches a real checkout, so the gate is unaffected — but
`live.py`'s module docstring states the macOS omission behaviour as universal, and it isn't.)*

### 2.2 The filesystem-placement rule — a **correctness** rule, not a performance one

WSL2 has two filesystems: Linux-native ext4 (`~/…`) and the Windows drives mounted at `/mnt/c/…`
(DrvFs). **The switchboard checkout must live on the Linux-native side.** This was previously
written up as a speed footgun. It is more than that — on DrvFs two "dissolved" blockers come back:

- **F5, symlinks.** `broker.py:1116` `dst.symlink_to(src)`. On DrvFs that is a real NTFS symlink,
  needing `SeCreateSymbolicLinkPrivilege` — Windows Developer Mode or admin, the exact constraint
  the §1 table says has no Linux-side equivalent. And it fails **silently**: `broker.py:1117-1118`
  catches `OSError` into a `link_failed` store event and continues, so `.switchboard`/`CLAUDE.md`
  config linking is simply absent with no error surfaced.
- **M6, case-folding.** DrvFs is case-insensitive by default; `live.py:136` compares path
  components case-**sensitively**. That is the NTFS trap M6 flagged, reappearing under a Linux
  `sys.platform`.
- **B1/B7, `flock`.** The 8 lock sites over DrvFs are unverified in either direction.

Plus the original performance point: DrvFs crosses the Windows-filesystem boundary on every
operation and is 10–100× slower, and switchboard is stat-heavy. So the failure mode is
**silently-wrong or slow**, not loudly broken — which is what makes it easy to fall into by habit
and easy to miss. This must be a loud, explicit setup instruction. *(DrvFs symlink privilege and
case-insensitivity are documented WSL behaviour; not re-measured here — no WSL2 box. See §6.)*

### 2.3 The `sb block` doorbell is silent on a stock WSL2 distro

switchboard's only path from a blocked agent to the human is `broker.py:6489-6493` `_surface()` →
`herdr.notify()` → `herdr notification show`. herdr routes that on `toast.delivery`
(`src/app/api.rs:1192-1236`), and two of the three routes have no working backend on a stock WSL2
Ubuntu:

| Route | On WSL2 | On macOS |
|---|---|---|
| `herdr` (in-app toast) | **Works** | Works |
| `terminal` | **Nothing shown.** `src/terminal_notify.rs:11-31` recognises only Ghostty, iTerm2, Kitty, WezTerm. **Windows Terminal is not in that list** — and it is the terminal `wsl --install` hands the user | Works (iTerm2/Ghostty/Kitty/WezTerm) |
| `system` | **Nothing shown** unless `notify-send` (`libnotify-bin`) is installed *and* a notification daemon is on the session bus; `platform/linux.rs:534-556` also returns early with no `DISPLAY`/`WAYLAND_DISPLAY` | Unconditional — `platform/macos.rs:583-597` falls back to `osascript`, always present |

**And switchboard cannot tell.** `_surface` catches only `HerdrError`, while herdr encodes
`{"shown": false, "reason": "no_foreground_client"}` as a **successful** response
(`api.rs` → `encode_success`) and `herdr.notify()` discards the body entirely
(`herdr.py:1131-1134`). No `notify_failed` event, no log line. The doorbell rings into nothing and
the store records that it rang. The audible cue has the same shape: `src/sound.rs:299-323` tries
`paplay`/`pw-play`/`ffplay`/`mpg123`/`mpv`, none in a stock WSL2 image, against macOS's
always-present `afplay`.

**Mitigation, and it belongs in the setup guide (§3).** The `herdr` route is the only one with a
working backend out of the box. Two ways to select it, and for this audience the **first is the
right instruction**:

1. **In herdr's settings UI** — Notifications → `herdr`. The four choices there are exactly
   Off / herdr / terminal / system (`src/app/input/settings.rs:19,76-91`, `SaveToastDelivery`).
2. By hand, in `~/.config/herdr/config.toml` (`src/config/io.rs:29-33,59-67,172`):
   ```toml
   [ui.toast]
   delivery = "herdr"
   ```

**The section is `[ui.toast]`, not `[toast]`** — `toast` is a field of `UiConfig`
(`src/config/model.rs:863-864`), pinned by herdr's own round-trip test at
`model.rs:1638-1652`. This matters more than a typo usually would: `Config` carries **no**
`#[serde(deny_unknown_fields)]` (zero hits in `model.rs`), so a stray top-level `[toast]` table is
**silently ignored**, `herdr config check` passes, delivery stays at its default `Off`, and
`sb block` is permanently silent — the exact failure this section exists to prevent, wearing the
disguise of a config file that looks correct. (Earlier drafts of this plan had it wrong. Also note
there is no `herdr config set` verb — `herdr config` has only `check` and `reset-keys`,
`src/cli/spec.rs:138-142`.)

For desktop toasts or sound instead: `sudo apt install libnotify-bin` (plus a notification daemon)
for the `system` route, and `sudo apt install pulseaudio-utils` for sound. The `terminal` route
cannot be made to work under Windows Terminal at all.

*Honest scoping:* herdr's default `delivery` is `Off` (`src/config/model.rs:59-65`), so this is a
regression relative to a user who has **configured** notifications — which on macOS is the working
setup today, and is the setup the blocking protocol assumes. Not re-tested live; no WSL2 box.

### 2.4 Setup is a much bigger ask than "download an app" — and this is the largest real cost

Earlier drafts called this "~one-command install". That phrase is withdrawn. Counted honestly, a
non-developer has to do **all** of the following, in order, with no step optional:

one Administrator PowerShell command + a reboot → possibly a BIOS virtualization toggle → a distro
first-run (Linux username/password) → `apt update` **then** `apt install` → a piped-curl herdr
install with a `PATH` caveat that reads as "it didn't work" → a Claude Code install → a
**browser-based login with no browser** (WSL2 has no `xdg-open` handler by default, so it is a
copy-the-URL-into-Windows step) → `git clone` → a **hand-made symlink**, because switchboard has no
install procedure at all (§3.7) → two `git config --global` lines, or every agent's first `sb done`
fails to commit → a settings change in a TUI (§2.3) → and knowing that `sb start` runs in *their
own project repo*, not in the switchboard checkout they just cloned.

None of it is hard for a developer. All of it is new for someone who isn't, and several steps fail
**silently or misleadingly** rather than with an error — which is what makes this a real cost and
not just a long list. §3 is written to close each of these; **writing and then validating that
guide on a real Windows box is the single largest piece of work this plan asks for**, larger than
the code fix in §2.1.

### 2.5 Encoding hygiene — worth doing anyway, and **not** zero-risk

The native audit enumerated, by AST pass, **26 `open()`/`read_text()` sites with no
`encoding="utf-8"` (F9)** and **26 `subprocess(..., text=True)` sites with no `encoding=` (F12)**,
plus F7b (`hooks.py:157,160`) and the stdio pair F10/F11. These mojibake on any non-UTF-8 locale —
a **latent POSIX bug today** (`LC_ALL=C`, minimal containers), not a Windows one. WSL2's default
locale is UTF-8, so none of them block it.

F9/F12/F7b are true POSIX no-ops and cheap. **F10/F11 are not.** Measured on this box:

```
sys.stdout.errors                       -> surrogateescape
sys.stdout.reconfigure(encoding='utf-8'); sys.stdout.errors -> strict
hasattr(io.StringIO(), 'reconfigure')   -> False
```

A bare `reconfigure(encoding=…)` (a) flips the stdio error handler `surrogateescape → strict`,
reintroducing on POSIX the exact failure F11 exists to fix, and (b) raises `AttributeError` under
`capsys`/`redirect_stdout`, on every platform. So F10/F11 must pass `errors=sys.stdout.errors` /
`errors=sys.stdin.errors` **and** be `getattr`-guarded. See the native plan's F10/F11 hazard note.

**These, plus §2.1, are the only switchboard code changes this plan recommends.** §2.1 is required
to run usefully under WSL2; §2.5 is not, and should land regardless of Windows.

## 3. Setup guide (WSL2, for a non-technical user)

**Read this first.** Steps marked **[W]** are Windows-side and are documented behaviour, *not
validated on a real box* — they are the ones §6 says still need a machine. Steps marked **[L]** are
Linux-side and are verified against switchboard's and herdr's source in this PR.

**Prerequisite for the whole guide: the §2.1 `lsof` fix (`-F pcnf`) ships in the repo first.** It
is a one-character change to `switchboard/live.py`; a setup guide must never ask its reader to
hand-patch a source file, and an earlier draft of this section did exactly that.

### Part 1 — Windows: get a Linux

1. **[W] Enable WSL2 + Ubuntu.** Open **PowerShell as Administrator**, run `wsl --install`, reboot.
   - **What success looks like:** it downloads, then asks you to reboot, then installs Ubuntu.
   - **If it prints a wall of usage/help text instead, it did not install.** That is the known
     Windows 10 pre-servicing-update shape and it does not report an error. Recovery:
     `wsl --set-default-version 2`, then install Ubuntu from the Microsoft Store.
   - Distro download goes through the Microsoft Store / winget, so a Store-blocked or
     corporate-managed machine can fail here.
   - If virtualization is off, enable it in the BIOS/UEFI (one-time). Windows 10 **Home** is fine —
     WSL2 needs the Virtual Machine Platform, not Hyper-V Pro.
2. **[W] Verify before going on:** `wsl -l -v` should list your distro at **VERSION 2**.
3. **[W] Open Ubuntu** (Start menu → "Ubuntu", or a Windows Terminal Ubuntu tab). Set the Linux
   username and password at the first prompt.

### Part 2 — Ubuntu: prerequisites

4. **[L] Update package lists *first*, then install.** On a fresh WSL Ubuntu the package lists are
   empty and `apt install` alone fails with "Unable to locate package":
   ```
   sudo apt update
   sudo apt install -y git curl lsof bubblewrap libnotify-bin pulseaudio-utils
   ```
   `curl` is needed by herdr's installer; `bubblewrap` by Claude Code's WSL2 sandbox
   (`researcher-wsl2-viability-findings.md` §2); `lsof` by §2.1; the last two by §2.3.
5. **[L] Check the Python floor — it is hard, not a preference:**
   ```
   python3 -V
   ```
   **3.11 or newer is required.** `switchboard/config.py:41` imports `tomllib`, which is 3.11+; on
   3.10 *every* `sb` command dies on its first line. Ubuntu 24.04 ships 3.12 and is fine. **Ubuntu
   22.04 ships 3.10 and will not run switchboard** — if `python3 -V` says 3.10, install a newer
   Ubuntu rather than trying to work around it. (Note the tension with §2.1: 22.04's older `lsof`
   is the one that *doesn't* need the fix. 24.04 + the fix is the supported combination.)
6. **[L] Set your git identity, or every agent's first `sb done` fails.** `sb done` commits, and a
   fresh Ubuntu has no identity configured:
   ```
   git config --global user.name  "Your Name"
   git config --global user.email "you@example.com"
   ```
7. **[L] Install herdr:**
   ```
   curl -fsSL https://herdr.dev/install.sh | sh
   ```
   It installs to `~/.local/bin` and only **warns** if that is not on `PATH`
   (`website/install.sh:68-86`). On Ubuntu, `~/.profile` adds `~/.local/bin` only if the directory
   existed at login — so straight after installing, `herdr` is often `command not found`, which
   reads like a failed install and isn't. **Close the terminal and open a new one**, then
   `command -v herdr`. Both `linux/x86_64` and `linux/aarch64` are supported
   (`install.sh:24-28`), so ARM Windows laptops are covered.
8. **[L] Install Claude Code** (its Linux/WSL2 install). **[W-ish] The login is browser-based and
   WSL2 has no default browser handler** — expect to copy the URL out of the terminal and paste it
   into a Windows browser. This is the step non-developers stall on.

### Part 3 — switchboard: there is no installer, so this is the real procedure

9. **[L] Clone on the Linux side — and check which side you landed on.** §2.2 is a correctness
   rule, and it fails *silently* if you get it wrong:
   ```
   cd ~
   git clone <switchboard-repo-url> switchboard
   cd ~/switchboard && pwd
   ```
   **`pwd` must start with `/home/`. If it starts with `/mnt/`, you are on the Windows side —
   stop and re-clone under `~`.** It will appear to work either way; that is the problem (§2.2).
   Natural ways to land on the wrong side: opening the folder from File Explorer, "Open in
   Terminal" from a Windows directory, or launching VS Code from Windows. Use VS Code's **WSL**
   extension if you use an editor.
10. **[L] Put `sb` on your PATH — by hand, because nothing does it for you.** switchboard has **no
    packaging file and nothing to install it *as*** (`README.md:109-111`); `bin/sb` runs the
    checkout in place. The real mechanism is one symlink per machine, documented today only inside
    a code comment (`broker.py:3310`):
    ```
    mkdir -p ~/.local/bin
    ln -s ~/switchboard/bin/sb ~/.local/bin/sb
    command -v sb        # must print /home/<you>/.local/bin/sb
    ```
    **Skip `pip install -r requirements.txt`.** It is optional (`rich` buys the panelled board and
    nothing else) and on Ubuntu 24.04 it fails anyway: `python3-pip` is absent from the WSL rootfs
    and 24.04's system Python is externally managed (PEP 668).
11. **[L] Turn the doorbell on, or `sb block` is silent.** herdr settings → Notifications →
    `herdr`. See §2.3 for why, and for the `[ui.toast]` TOML form if you prefer editing the file.

### Part 4 — run it, and check that it worked

12. **[L] Verify the install:**
    ```
    sb doctor        # checks herdr, its version, and integration conflicts
    ```
    Two things it is checking for: switchboard requires herdr **≥ 0.8.0**
    (`defaults/settings.toml:654`), and herdr's bundled **`claude` integration must stay
    uninstalled** — if present, `check()` refuses to start, because it claims pane session
    ownership and makes herdr *silently* reject switchboard's state writes
    (`herdr.py:320-335`, `1049-1052`). A fresh box is clean. **Do not** run `herdr integration
    install claude`. *(`scripts/00-preflight.sh:26` currently tells readers to do exactly that. It
    is stale and it will break the install — an existing switchboard bug, unrelated to Windows,
    reported separately.)*
13. **[L] Start a fleet — in your own project, not in the switchboard checkout.** This is the
    single most likely misunderstanding for someone who has just spent ten minutes cloning
    switchboard:
    ```
    cd ~/my-project      # a git repo, with at least one commit
    sb start
    ```
    `sb start` is the only way a dispatcher is ever made (`README.md:27`). The store lives under
    the project repo's shared `.git`, and `sb delegate` creates git worktrees of *that* repo. The
    default base branch is `origin/main`, falling back to a local `main`
    (`defaults/settings.toml:139`, `broker.py:1815-1817`) — a project on `master` with no remote
    fails at the first delegate.

### Part 5 — day 2

14. **Getting back in tomorrow:** run `herdr` to reattach; `ctrl+b q` detaches without killing
    anything. The herdr server outlives your terminal (real POSIX `setsid`).
15. **Sleep, and `wsl --shutdown`:** `wsl --shutdown` stops the whole Linux VM and everything in
    it. Whether a running fleet survives Windows sleep/hibernate, WSL's idle timeout, or the clock
    jump on resume is **the biggest open question in this plan** — see §6. Until someone tests it,
    assume an overnight fleet may not be there in the morning.
16. **Where your state lives:** SQLite under the project repo's shared `.git`, so every worktree
    finds the same one (`README.md:115-118`). It is operational state and disposable by
    construction — losing it does not lose your code, which is in git.
17. **Updating:** `herdr update` for herdr; `git pull` in `~/switchboard` for switchboard (the
    symlink keeps working); Claude Code's own updater. After a herdr update, re-run `sb doctor` —
    switchboard pins a *minimum* herdr version, and newer-than-tested is not the same as verified
    (`herdr.py:9` notes the protocol pin).

## 4. Options compared — why WSL2, and the one real runner-up

Full ranked table + citations in `windows-support/researcher-windows-options-findings.md`. Summary:

| Rank | Option | Verdict |
|---|---|---|
| **1** | **WSL2** | Recommended. Rides herdr's stable Linux binary, one-character switchboard fix (§2.1) and nothing else required, runs locally (no cloud bill, no second machine, works offline). **Not** a one-command install for a non-developer — see §2.4. |
| 2 | **Remote into a Linux host, attach from Windows** | herdr's *documented intended* Windows story (Windows = client, Linux = host; Windows-as-host is unsupported). Wins over WSL2 **only if** the user already wants a persistent Linux box that outlives the laptop (home server; agents running overnight). Otherwise it's more operational burden (uptime/cost/SSH) for the same result. |
| 3 | Cloud dev box (Codespaces / cloud VM) | Same mechanism as #2, no box to maintain, but a recurring bill and always-online. Only if zero local footprint is wanted. |
| 4 | Full Linux VM (Hyper-V/VirtualBox) | Strictly heavier than WSL2 for the identical result. Essentially never wins here. |
| 5 | Docker / devcontainer | Untested for herdr's long-lived-server + pty model; requires WSL2 as its backend anyway, so it can only be worse than WSL2 for one user. |
| **6** | **Native Windows (the fallback plan)** | Highest risk: stacks herdr's *experimental-beta* Windows support under switchboard's *large, unbuilt* port. Only revisit if herdr's Windows support goes stable AND a native-only experience is specifically wanted. |
| 7 | Dual-boot Linux | Real disk-partition data-loss risk + loses Windows while working. No. |

---

## 5. Recommendation

**Run switchboard in WSL2.** It is the cheapest correct answer to "gain Windows support," it's the
lowest-risk (stable herdr, no unbuilt port), and it runs entirely on the user's own machine. The
deliverable is therefore a **setup guide** (§3) plus **one required code fix** (§2.1, one
character) and a few **optional code-hygiene fixes** (§2.5), not an engineering port.

Say the size of that setup guide honestly, though: it is ~17 steps, several of which fail silently
or misleadingly (§2.4), and it is the **largest** piece of work here — larger than the code. Two
things must happen before anyone is handed it: the §2.1 fix lands in the repo, and **the guide is
walked end-to-end on a real Windows machine** (§6). Handing this document to a non-developer today
would not work; it is the specification for a guide, now written as one, not a validated one.

Offer **remote-into-Linux** as the alternative for the specific user who wants a persistent Linux
box independent of the laptop. Keep the **native-Windows** plan parked as the "if herdr's Windows
support ever stabilizes and a native-only experience is wanted" fallback.

---

## 6. What is unverified (no real Windows/WSL2 box was available)

All findings are from source (switchboard + herdr) and documented WSL2/Claude Code behaviour, not
a live WSL2 run. High-confidence because the platform gating is mechanical (`cfg(windows)` /
`sys.platform`), but not empirically closed. Specifically still needs a real WSL2 box to confirm:

- **Does the long-lived herdr server survive WSL2's VM lifecycle?** The biggest WSL2-vs-Linux
  unknown, and the one this plan can least afford. On bare-metal Linux `setsid`
  (`herdr/src/platform/mod.rs:73-85`) settles it. Under WSL2 the *distro VM* lifecycle is Windows'
  — `vmIdleTimeout`, `wsl --shutdown`, host sleep/hibernate suspending the VM, and the wall-clock
  jump on resume that switchboard's own deadlines sit on (`herdr.py:1096-1112` uses `time.time()`).
  switchboard's model is agents running overnight and blocked agents waiting hours for a human, so
  this is directly load-bearing. Not a source question — it needs a real box.
- **§3 walked end-to-end on a real Windows machine.** Every step marked **[W]** there is
  documented behaviour or inference, never run: `wsl --install`'s help-text-instead-of-installing
  failure on older Windows 10, the Store/winget download path, and Claude Code's browser login with
  no browser handler. The **[L]** steps are verified against source, not against a live Ubuntu —
  `apt update` ordering, the `~/.local/bin` PATH-at-login behaviour, and PEP 668 on 24.04 are all
  documented Ubuntu/apt behaviour rather than measured here.
- **switchboard's missing install story.** §3.10 documents the one-symlink mechanism from a code
  comment (`broker.py:3310`) because nothing else documents it. Whether that should instead become
  a real install step in the repo is a decision this plan surfaces and does not make.
- The §2.3 doorbell mitigation actually alerting a human under Windows Terminal + WSL2.
- **Clipboard *reads*** through a WSL2 terminal. (Narrowed: clipboard *writes* are settled by
  source — herdr deliberately prefers OSC 52 under WSL specifically so Windows Terminal's clipboard
  history is populated. Reads offer only `wl-paste`/`xclip`/`xsel` gated on
  `WAYLAND_DISPLAY`/`DISPLAY`, with no OSC 52 fallback. Neither direction is a switchboard
  dependency — switchboard sends text server-side via `agent prompt`.)
- herdr's foreground-process agent detection (`herdr/src/platform/linux.rs:287+`) under WSL2.
  Expected to work — WSL2 is a real kernel with a real `/proc` — and herdr ships an opt-in
  `HERDR_PROCESS_DETECTION=child-groups` fallback if not. Low risk; switchboard mostly drives
  agent state explicitly.
- Claude Code's current-version WSL2 sandbox/hooks/git specifics (documented, not re-tested).
- The default WSL2 distro's locale (`UTF-8`) and default shell (`bash`) in practice (standard for
  Ubuntu, assumed not measured).
- Real DrvFs behaviour for switchboard's specific I/O if a user wrongly puts the repo on
  `/mnt/c/…`: the symlink-privilege failure (§2.2), the case-folding comparison, `flock` over
  DrvFs, and the slowdown numbers. All four are reasoned from documented WSL behaviour, not run.
- **The pane/agent/fleet surface on Linux at all.** Linux CI has no herdr and no tmux
  (`tests.yml:17-21`); the macOS leg is what covers it. Nothing in this plan closes that — a WSL2
  user is the first person exercising it. This is the largest single unknown here and it is not a
  Windows question, it is a Linux one.
- The §2.1 `lsof` fix under a **real** WSL2 kernel. It was measured on Docker-for-Mac's LinuxKit
  VM, which is a real Linux kernel but not WSL2's; the lsof revision is the variable and Ubuntu
  24.04 is Ubuntu 24.04, so confidence is high, but it is one `wsl --install` away from being
  closed properly.

---

## Appendix — supporting docs (all in this PR)

- `windows-support/lsof-linux-measurement.md` — the measured lsof-revision finding behind §2.1,
  and why the tracked `test_live.py` skip is right and the liveness audit's headline is wrong.
- `windows-support/researcher-wsl2-viability-findings.md` — the blocker-by-blocker WSL2
  verification + gotcha hunt.
- `windows-support/researcher-windows-options-findings.md` — the ranked options comparison.
- `windows-support/native-port-plan.md` — the full native-Windows port plan (the parked fallback),
  and under `windows-support/audits/` the six concern-scoped native audits + the herdr-on-Windows
  gate finding it was built from.
- `windows-support/review/` — the adversarial review of the (native) plan; a fresh review of THIS
  WSL2-first plan is run before the PR is finalized.

Status (2026-08-22): scope corrected to WSL2-first; supporting research verified; **adversarial
review rounds 1-3 folded in**. Round 1: F1 demoted to *measured broken* with a one-character fix;
§1 reframed to Windows-gated only; §2.2 rewritten as a correctness rule; §2.5's "zero-risk"
retracted. Round 2: "herdr under WSL2 is clean" replaced with herdr's three real runtime WSL
divergences; new §2.3 for the silent `sb block` doorbell; VM lifecycle added to §6. Round 3: §3
rewritten from an outline into an actual 17-step guide with literal commands, [W]/[L] validation
markers and a day-2 section; the `[toast]` config section corrected to **`[ui.toast]`** in §2.3
(the wrong one is silently ignored — the plan had reintroduced the very failure §2.3 prevents);
"~one-command install" withdrawn from §2.4 and §4. Further rounds pending before PR #171 is
updated.
