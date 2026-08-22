# Every way to run switchboard on a Windows PC — ranked comparison

Scope: breadth survey per brief (`.switchboard/briefs/researcher-windows-options/brief.md`).
Read-only, no code touched. Sources: herdr source/docs at `/Users/andrew/Code/herdr`
(commit as checked out), `notes/windows-support-plan.md`,
`notes/windows-support/audits/researcher-herdr-on-windows-findings.md` (this repo, both
already-verified by a sibling researcher), and general Claude Code / WSL2 / Docker Desktop
public documentation reasoned from written knowledge (no network access used — flagged
where it matters). I do not have a Windows box; anything needing hands-on Windows testing
is flagged as unverified.

## The decisive fact

herdr's own docs are explicit about its *intended* Windows story, and it is **not** "port
everything natively":

> "Remote attach supports Linux, macOS, and Windows local clients connecting to Linux or
> macOS hosts... **Windows is not supported as the remote host.**"
> — `docs/next/website/src/content/docs/persistence-remote.mdx:66`

> `herdr --remote` to Linux/macOS hosts: **beta** (supported)
> Windows as a `herdr --remote` **target host**: **unsupported**
> — `docs/next/website/src/content/docs/windows-beta.mdx` (supported/not-supported tables)

So herdr's authors have already picked a lane: Windows machine = client only, driving a
Linux (or macOS) box that does the real work. That single fact reorders this whole
comparison — it's why WSL2 (a Linux box that happens to live inside the Windows machine)
and "remote into Linux, attach from Windows" both sit above native Windows, and why native
Windows carries a risk the others don't: it's building on a target herdr itself won't yet
run as a host.

## Ranked comparison

| Rank | Option | Full stack works? | Setup effort (1–5, 1=easiest) | Day-to-day friction | Risk/fragility | Beats WSL2 when… |
|---|---|---|---|---|---|---|
| 1 | **WSL2** | Yes — herdr's **stable** Linux binary, same install (`curl \| sh`), same code path as macOS/Linux. Only WSL-specific note in herdr's docs is a cosmetic cursor-drawing default (`troubleshooting.mdx:17`), not a functional gap. | 2 — `wsl --install` (built into Windows 10 2004+ / 11), one reboot, then normal Linux install inside it. Microsoft has driven this to near one-command since ~2021. | Low once set up: a Windows Terminal tab running Ubuntu; user learns "open WSL" as a habit. Occasional friction: file paths across the Windows/Linux boundary, remembering to work inside the Linux filesystem for performance. | Low — herdr treats it as ordinary Linux; switchboard needs zero Windows-specific code. Risk is entirely "can this non-technical user get through `wsl --install`", not the software. | — (baseline) |
| 2 | **Remote into a Linux host, attach from Windows** | Yes — this is the path herdr's docs describe as supported today (`persistence-remote.mdx:38-93`, `windows-beta.mdx` "supported in beta" table: "`herdr --remote` to Linux/macOS hosts: beta"). Windows client uses its normal OpenSSH; Herdr bridges clipboard image paste remotely. | 3–4 for the *user's* one-time setup (`herdr --remote host`, needs SSH access already configured to *some* Linux box) — but the Linux box itself (a home server, a cloud VM, or WSL2) is somebody else's problem to provision and keep alive. If that box is a cloud VM the user doesn't own yet, effort jumps to 4–5. | Low day-to-day (`herdr --remote workbox` from Windows Terminal), but **depends on that remote box staying up and reachable** — home server power/network, or a recurring cloud bill. Windows OpenSSH lacks herdr's control-socket reuse (`persistence-remote.mdx:68`), so slightly more SSH prompt friction than Linux/macOS-to-Linux. | Medium — not a herdr code risk (this path is genuinely supported), but an *operational* risk: uptime/networking/cost of the remote box is now the user's job, and it's one more moving part than WSL2 (which never leaves the laptop). | The user already has (or wants) a persistent Linux box they'd keep running anyway — e.g. a home server, or they want their agents to keep running when the laptop is closed/asleep. If that box is itself WSL2, this degenerates to option 1 plus SSH overhead for no benefit — don't do that. |
| 3 | **Cloud dev box (Codespaces / cloud Linux VM), attach from Windows** | Yes, same mechanism as #2 — herdr on the cloud box is a normal Linux install; Windows is just the SSH client (Codespaces' SSH endpoint or a bare cloud VM). Claude Code itself is well-documented as running fine in Codespaces/devcontainers. | 3 for a managed option like Codespaces (GitHub-hosted, no box to patch) if the user already has a GitHub account with Codespaces access; 4–5 for a self-managed cloud VM (security groups, SSH keys, OS updates all now the user's job). | Low day-to-day, but **recurring cost** (Codespaces/cloud VM billing) and a network dependency — no offline work at all, unlike WSL2 which runs locally. | Low-medium — same "genuinely supported" path as #2, plus Codespaces removes the "keep a home server alive" operational burden, at the price of a bill and requiring an internet connection at all times. | The user wants zero local install footprint at all, is fine paying a recurring cloud bill, and doesn't need offline access. Otherwise WSL2 is strictly less friction and free. |
| 4 | **Full Linux VM (Hyper-V/VirtualBox/VMware)** | Yes — it's just Linux, same as WSL2, herdr's stable path. | 3–4 — more manual than WSL2: enable Hyper-V or install VirtualBox, create a VM, install a Linux ISO, configure networking/shared folders. No one-line installer equivalent. | Medium — heavier resource footprint (dedicated RAM/disk allocation vs WSL2's dynamic sharing), separate "boot the VM" step, clunkier file sharing with the Windows host, no Windows-integrated terminal experience the way WSL2 gets via Windows Terminal. | Low functionally (same Linux binary), but strictly more setup and runtime overhead than WSL2 for the identical result. | Essentially never for this use case — WSL2 **is** a lighter-weight, better-integrated version of exactly this (a Linux kernel running under Windows), with a one-command installer Microsoft maintains. A full VM only wins if the user needs an isolation boundary WSL2 doesn't provide (e.g. testing against a specific unusual distro/kernel), which doesn't apply here. |
| 5 | **Docker Desktop / devcontainer** | Uncertain / likely degraded. herdr's pane model is a background server + ConPTY/PTY-backed panes with process-tree agent detection, live server handoff, and file-descriptor handoff (`windows-beta.mdx` "not supported" table lists "Unix file-descriptor handoff" and "Live server handoff" as unsupported *even natively* on Windows — a container adds another layer of process/PID-namespace indirection on top). No herdr doc describes or endorses a container deployment; this is unproven, not contradicted. | 4 — Docker Desktop itself requires WSL2 as its backend on Windows anyway (so the user needs WSL2 working *first*), then a devcontainer/Dockerfile for switchboard+herdr+Claude Code needs to be built and maintained (nobody has done this yet — it doesn't exist for this project). | Medium-high — persistent background server model doesn't map cleanly onto typical container lifecycle (containers are meant to be disposable; herdr wants a long-lived server process holding pane state across detach/reattach). Attaching a **Windows terminal client** to a herdr server running *inside* a Linux container is architecturally the same problem as "remote into Linux" (#2/#3) but self-inflicted extra complexity for no isolation benefit an individual non-technical user needs. | High — this is the one option nobody has built or tested for switchboard; "does herdr's pane/pty/interactive model even work in a container" is an open question the brief itself flags, and I found no evidence either way in herdr's docs or CI (CI tests native Linux/macOS/Windows runners, not containers). | Only if the goal were multi-tenant isolation or reproducible CI-style environments, not "one person's Windows PC." For a single non-technical user this only adds a layer (Docker Desktop) on top of the WSL2 layer it already requires, for no benefit. |
| 6 | **Native Windows** (PR #171's plan) | Partially — herdr genuinely spawns ConPTY panes on native Windows and CI smoke-tests it (`H1` in the audits doc: real, CI-tested, but **"experimental beta," not "stable"** — not in herdr's tag-triggered release pipeline, only manual/preview builds). switchboard itself has **zero** Windows-specific code today; `notes/windows-support-plan.md` (885 lines) describes this as a comprehensive port across `sb`/broker/plugins/panel/sweep/board/hooks/worktrees with an explicit "zero regression to macOS/Linux" bar — i.e. a large, still-hypothetical engineering effort, not a shipped path. | 5 in one sense (once built, install would be simplest: no Linux layer at all) but the *precondition* — someone has to actually build and ship it — hasn't happened. As a thing the user could do **today**, this option doesn't exist yet. If it existed: still 3-4, because herdr's Windows installer isn't in the signed/SmartScreen-clean stable channel (`windows-beta.mdx` "not supported" table: "Signed binary / SmartScreen avoidance: unsupported") — a non-technical user would hit a scary "Windows protected your PC" warning during install. | Unknown/likely medium-high even once built — herdr's beta docs list several partial/unverified capabilities that would directly touch switchboard's needs: live cwd tracking after shell `cd` is "partial," clipboard image paste to local panes is "unverified," and the default shell is PowerShell (not cmd.exe, contradicting the prior migration note switchboard's plan corrected). | **Highest of all options.** Two independent risk layers stack: (a) herdr's own Windows support is explicitly beta and "not a commitment" per its docs — herdr's authors could keep it beta or reduce it; (b) switchboard's own port is unbuilt, large-surface-area, and the plan itself flags multiple hard blockers (SIGHUP/SIGWINCH crashes, a bash-string readiness check, `select.select` on stdin, an `os.access(X_OK)` lie) that need real engineering, not configuration. | Only if/when herdr's Windows support graduates out of beta **and** someone actually builds switchboard's native port **and** the user specifically wants to avoid running any Linux layer at all. None of those are true today. For a non-technical user asking "how do I get this working on my Windows PC," this is the slowest, riskiest, and currently-nonexistent option. |
| 7 | **Dual-boot Linux** | Yes, technically — it's just Linux, same stable herdr path. | 5 — by far the highest-friction setup: partition the disk, install a full Linux distro alongside Windows, handle bootloader/driver issues, risk to existing Windows install/data during partitioning. Genuinely risky for a non-technical user to do unsupervised. | High — user loses Windows entirely while working (no Windows apps, browser tabs, etc. without rebooting); rebooting to switch contexts is real friction for anyone who isn't purely living in a terminal. | Low functionally, but the *setup itself* carries real data-loss risk (partitioning mistakes) that none of the other options have — every other option is fully reversible/uninstallable without touching the Windows install. | Essentially never for this user. Dual-boot only makes sense for someone who wants Linux as their primary OS and Windows as the occasional exception — the opposite of "get switchboard working on my Windows PC" while keeping Windows as home base. WSL2 gives the same Linux environment with none of the reboot friction or partition risk. |

## Recommendation

**WSL2, with no serious contender for a single non-technical user on one Windows PC.**

- It rides herdr's **stable**, fully-tested Linux binary — the same code path already
  proven on macOS/Linux — so switchboard needs zero new Windows-specific code and inherits
  none of native Windows's beta risk.
- Setup is close to one command (`wsl --install`, built into Windows since 2020/2021) plus
  the normal Linux `curl | sh` install — the lowest setup burden of any option that isn't
  "do nothing."
- Everything runs locally: no recurring cloud bill, no dependency on a second machine
  staying powered on, no internet requirement once installed — unlike both remote-into-Linux
  options (#2, #3).

**Runner-up: remote into a Linux host, attach from Windows (rank 2).** This is the path
herdr's own docs actually describe as supported today (Windows as a client attaching to a
Linux/macOS remote host) — it is not a hack, it's the documented intended shape of Windows
support. **It wins over WSL2 only if the user already has, or specifically wants, a
persistent Linux box that keeps running independent of the Windows laptop** — e.g. they
want their agents to keep working overnight while the laptop sleeps, or they already run a
home server for other things. Absent that specific want, it's strictly more operational
burden (a second machine or a cloud bill to keep alive, plus SSH setup) than WSL2 for the
same herdr functionality, so it should be offered as an option, not the default.

**Native Windows (PR #171's plan) should not be pursued for this user.** It sits on two
stacked risks neither of the top two options carries: herdr's own Windows support is
explicitly experimental beta with no commitment to stabilize, and switchboard's port is a
large, currently-unbuilt engineering effort (885-line plan, multiple unresolved hard
blockers) on top of that. It could become viable later if herdr's Windows support
graduates to stable — worth revisiting then, not now.

**Docker/devcontainer and dual-boot rank lowest** for this specific ask: Docker adds a
second layer of untested complexity on top of a WSL2 backend it already requires (so it
can only ever be strictly worse than WSL2 for a single user), and dual-boot introduces
real setup risk (disk partitioning) and daily friction (losing Windows access without a
reboot) that no other option has.

## What I could not verify

- No Windows box was available; everything above is source/doc reading, not a live test.
  In particular, WSL2's "close to one command" setup effort and Docker Desktop's
  container/PTY behavior are general technical knowledge, not something I ran or confirmed
  against this specific herdr/switchboard stack.
- I did not check Claude Code's own documentation for Windows/WSL2/Codespaces support
  specifics (e.g. any Windows-native Claude Code caveats) — I reasoned from general
  knowledge of Claude Code running fine under WSL2 and devcontainers, not a citation.
- Whether a devcontainer for switchboard+herdr+Claude Code has ever been attempted:
  I found no evidence either way in this repo or herdr's repo — absence of evidence, not
  evidence it fails.
