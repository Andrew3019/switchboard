# Running switchboard on a Windows PC — the plan

Investigation only, 2026-08-22. No production code changed. **The ask was "gain Windows
support."** This document answers that ask the cheapest correct way, after correcting an earlier
scope error (see the note below).

## TL;DR

**Recommendation: run switchboard inside WSL2** (Windows Subsystem for Linux 2 — a real Linux
kernel Microsoft ships built into Windows). switchboard already runs on Linux and is CI-tested
there; WSL2 *is* Linux, so this needs **essentially zero switchboard code changes**. It rides
herdr's **stable** Linux support and sidesteps herdr's experimental-beta *native*-Windows support
entirely. The cost is not code — it's a one-time setup and one placement rule (keep the repo on
the Linux side, not `C:\`).

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

## 1. Why WSL2 works — every native blocker dissolves

The native-port plan found ~30 platform-specific blockers. **Every one of them is gated on a
Windows-specific code path** — Python `sys.platform == "win32"` / `os.name == "nt"`, or herdr's
Rust `cfg(windows)` compile-time target. A process inside WSL2 runs on a **real Linux kernel**;
the Python interpreter reports `linux` and the herdr binary is a genuine
`x86_64-unknown-linux-gnu` build. So none of those Windows branches ever execute — this is not
emulation or a shim, these specific lines of code simply do not run. (Full verification, blocker
by blocker, in `windows-support/researcher-wsl2-viability-findings.md`.)

| Native blocker (native-plan ref) | Under WSL2 | Confidence |
|---|---|---|
| `import fcntl` (broker/plugins/panel/sweep/plans) — B1/B7 | Real Linux stdlib module | High |
| `import termios`/`tty`, raw-mode input, `select` on stdin — B2/F3/F4 | Real Linux tty layer | High |
| `signal.SIGHUP` / `SIGWINCH` — B3/B4 | Both defined on Linux; WSL2 pty delivers `SIGWINCH` on resize | High |
| `lsof` / `ps -Ao` / `vm_stat` — F1/F2 | `lsof` is one `apt install`; `stats.py` already has `_available_linux()` reading real `/proc` | High |
| symlinks needing Developer Mode — F5 | Native POSIX symlinks; no "Developer Mode" concept on the Linux side | High |
| `.cmd`/shebang/`os.access(X_OK)`, `shlex.quote`, bash-only `_ready_pane`, `exec` — B5/B6/F6/F7/F8 | Panes are POSIX shells running shebang scripts with real exec bits | High |
| ConPTY / `msvcrt` / `start_new_session` discarded — F13 | N/A — these are *native-Windows* API problems; WSL2 uses real POSIX `setsid`/pty | High |
| `psutil` adoption (native fix D1) | Not needed — the existing Linux `ps`/`/proc` paths run | High |

**herdr under WSL2 is clean** (verified from source at `/Users/andrew/Code/herdr`): its pty is the
`portable-pty` crate's real Unix `openpty` behind a compile-time `cfg(unix)` gate; its IPC socket
lives under `~/.config/herdr` with **no systemd / `XDG_RUNTIME_DIR` dependency** (important —
WSL2 doesn't run systemd by default); it does **no** inotify file-watching. herdr's Windows *beta*
status is about its native-Windows (ConPTY/PowerShell) code path — running herdr as a Linux binary
under WSL2 never touches it.

**Claude Code under WSL2** is a documented/supported way to run on Windows, and its sandbox works
under WSL2 (but **not** native Windows) — another point in WSL2's favor.

---

## 2. The real costs — not code, but setup and one placement rule

WSL2 is near-zero *code* work; it is not zero *friction*. Three honest costs:

1. **The filesystem-placement footgun (the one thing that must be gotten right).** WSL2 has two
   filesystems: the Linux-native ext4 (`~/…`, i.e. `/home/<you>/…`) and the Windows drives mounted
   at `/mnt/c/…`. **The switchboard checkout — with its `.git/agentflow` STORE and `.switchboard`
   symlinks — must live on the Linux-native side (`~/…`), not `/mnt/c/…`.** On `/mnt/c/…` every
   file operation crosses the Windows-filesystem boundary and is 10–100× slower (switchboard is
   stat-heavy: STORE reads, symlink checks, pane polling), and inotify is unreliable there. The
   failure mode is *working-but-slow*, not broken — so it's easy to fall into by habit and easy to
   miss. This must be a loud, explicit setup instruction.
2. **Setup is a bigger ask for a non-technical user than "download an app."** It means: enable
   WSL2 (`wsl --install`, one reboot, occasionally a BIOS virtualization toggle), install a distro
   (Ubuntu), understand that files now live in two places, install Claude Code + switchboard
   *inside* the Linux environment, and open a WSL/Ubuntu terminal (or VS Code Remote-WSL) rather
   than PowerShell. None of this is hard for a developer; all of it is new for someone who isn't.
3. **A few residual encoding hygiene fixes are worth doing anyway** (independent of WSL2): the
   native audit found ~a dozen `open()`/`read_text()` calls with no `encoding="utf-8"` and no
   `sys.stdout.reconfigure(encoding="utf-8")` — these mojibake on any non-UTF-8 locale, a **latent
   bug on POSIX today** (`LC_ALL=C`, minimal containers), not just Windows. WSL2's default locale
   is UTF-8 so they don't block it, but they're cheap, zero-risk, and should land regardless. Same
   for the cosmetic `live.py` scope-invariant docstring note. **These are the only switchboard code
   changes this plan recommends — and none are required to run under WSL2.**

---

## 3. Setup guide (WSL2, for a non-technical user)

A step-by-step to hand the user. (Commands to be validated on a real Windows box — see §6.)

1. **Enable WSL2 + Ubuntu:** open PowerShell as Administrator, run `wsl --install` (installs WSL2
   + Ubuntu by default on Windows 10 2004+ / Windows 11), reboot. If virtualization is disabled,
   enable it in the BIOS/UEFI (one-time).
2. **Open Ubuntu** (Start menu → "Ubuntu", or a Windows Terminal Ubuntu tab). Set the Linux
   username/password when first prompted.
3. **Work on the Linux side.** Keep everything under your Linux home (`~/`). Do **not** clone into
   `/mnt/c/…`. (If using an editor, VS Code + the "WSL" extension edits Linux-side files correctly.)
4. **Install prerequisites inside Ubuntu:** git, Python 3.11/3.12, `lsof` (`sudo apt install
   lsof`), herdr (its normal Linux install), and Claude Code (its Linux/WSL2 install).
5. **Clone + install switchboard inside Ubuntu**, exactly as on macOS/Linux today. It runs as the
   CI-tested Linux build.
6. **Run it from the Ubuntu terminal.** herdr, panes, hooks, the board — all the normal Linux paths.

---

## 4. Options compared — why WSL2, and the one real runner-up

Full ranked table + citations in `windows-support/researcher-windows-options-findings.md`. Summary:

| Rank | Option | Verdict |
|---|---|---|
| **1** | **WSL2** | Recommended. Rides herdr's stable Linux binary, zero switchboard code, runs locally (no cloud bill, no second machine, works offline), ~one-command install. |
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
deliverable is therefore mostly a **setup guide** (§3) plus a couple of **optional code-hygiene
fixes** (§2.3), not an engineering port.

Offer **remote-into-Linux** as the alternative for the specific user who wants a persistent Linux
box independent of the laptop. Keep the **native-Windows** plan parked as the "if herdr's Windows
support ever stabilizes and a native-only experience is wanted" fallback.

---

## 6. What is unverified (no real Windows/WSL2 box was available)

All findings are from source (switchboard + herdr) and documented WSL2/Claude Code behaviour, not
a live WSL2 run. High-confidence because the platform gating is mechanical (`cfg(windows)` /
`sys.platform`), but not empirically closed. Specifically still needs a real WSL2 box to confirm:

- The exact `wsl --install` → herdr → Claude Code → switchboard end-to-end on a real machine.
- herdr's clipboard/OSC escape actually reaching the Windows clipboard through a given WSL2
  terminal.
- Claude Code's current-version WSL2 sandbox/hooks/git specifics (documented, not re-tested).
- The default WSL2 distro's locale (`UTF-8`) and default shell (`bash`) in practice (standard for
  Ubuntu, assumed not measured).
- Real DrvFs slowdown numbers for switchboard's specific I/O if a user wrongly puts the repo on
  `/mnt/c/…`.

---

## Appendix — supporting docs (all in this PR)

- `windows-support/researcher-wsl2-viability-findings.md` — the blocker-by-blocker WSL2
  verification + gotcha hunt.
- `windows-support/researcher-windows-options-findings.md` — the ranked options comparison.
- `windows-support/native-port-plan.md` — the full native-Windows port plan (the parked fallback),
  and under `windows-support/audits/` the six concern-scoped native audits + the herdr-on-Windows
  gate finding it was built from.
- `windows-support/review/` — the adversarial review of the (native) plan; a fresh review of THIS
  WSL2-first plan is run before the PR is finalized.

Status (2026-08-22): scope corrected to WSL2-first; supporting research verified; **fresh
adversarial review of this plan pending** before PR #171 is updated.
