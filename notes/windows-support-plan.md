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
  defaults to UTF-8 so they do not bite. See §2.4.

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
| encoding class — F7b/F9/F10/F11/F12 (~52 sites) | **Not Windows-gated — locale-gated.** Does not dissolve; WSL2's UTF-8 default means it does not bite. Latent POSIX bug regardless (§2.4) | Medium (rests on the distro locale, not on code paths) |
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

### 2.3 Setup is a bigger ask for a non-technical user than "download an app"

Enable WSL2 (`wsl --install`, one reboot, occasionally a BIOS virtualization toggle), install a
distro (Ubuntu), understand that files now live in two places, install Claude Code + switchboard
*inside* the Linux environment, and open a WSL/Ubuntu terminal (or VS Code Remote-WSL) rather than
PowerShell. None of this is hard for a developer; all of it is new for someone who isn't.

### 2.4 Encoding hygiene — worth doing anyway, and **not** zero-risk

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
to run usefully under WSL2; §2.4 is not, and should land regardless of Windows.

## 3. Setup guide (WSL2, for a non-technical user)

A step-by-step to hand the user. (Commands to be validated on a real Windows box — see §6.)

1. **Enable WSL2 + Ubuntu:** open PowerShell as Administrator, run `wsl --install` (installs WSL2
   + Ubuntu by default on Windows 10 2004+ / Windows 11), reboot. If virtualization is disabled,
   enable it in the BIOS/UEFI (one-time).
2. **Open Ubuntu** (Start menu → "Ubuntu", or a Windows Terminal Ubuntu tab). Set the Linux
   username/password when first prompted.
3. **Work on the Linux side.** Keep everything under your Linux home (`~/`). Do **not** clone into
   `/mnt/c/…`. (If using an editor, VS Code + the "WSL" extension edits Linux-side files correctly.)
4. **Install prerequisites inside Ubuntu:** git, Python 3.11/3.12, `lsof` and `bubblewrap`
   (`sudo apt install lsof bubblewrap` — neither is preinstalled; bubblewrap is what Claude Code's
   sandbox needs under WSL2, per `researcher-wsl2-viability-findings.md` §2), herdr (its normal
   Linux install), and Claude Code (its Linux/WSL2 install).
5. **Clone + install switchboard inside Ubuntu**, exactly as on macOS/Linux today.
6. **Land the §2.1 `lsof` fix** (`-F pcnf`) before relying on `sb cleanup` / `sb workspace close`.
   Without it they refuse on Ubuntu 24.04, permanently and by design.
7. **Run it from the Ubuntu terminal.** herdr, panes, hooks, the board — all the normal Linux paths.
   Expect the pane/agent/fleet surface to be exercised on Linux for the first time here (§1) — the
   Linux CI leg has never run it.

---

## 4. Options compared — why WSL2, and the one real runner-up

Full ranked table + citations in `windows-support/researcher-windows-options-findings.md`. Summary:

| Rank | Option | Verdict |
|---|---|---|
| **1** | **WSL2** | Recommended. Rides herdr's stable Linux binary, one-character switchboard fix (§2.1) and nothing else required, runs locally (no cloud bill, no second machine, works offline), ~one-command install. |
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
character) and a few **optional code-hygiene fixes** (§2.4), not an engineering port.

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
review round 1 folded in** — §1 reframed to Windows-gated only, F1 demoted to *measured broken*
with a fix, §2.2 rewritten as a correctness rule, §2.4's "zero-risk" retracted with counts
corrected to 26+26. Further review rounds pending before PR #171 is updated.
