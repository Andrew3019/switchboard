# Measured: `live.CWD_SCAN` is blind on the default WSL2 distro

Run 2026-08-22 by `proposer-wsl2-plan` during adversarial review round 1, in Docker on
macOS (Docker Desktop's LinuxKit VM). Reason: `notes/windows-support/audits/
researcher-process-liveness-findings.md` claimed the repo's own `tests/test_live.py:70`
skip and `.github/workflows/tests.yml:17-21` comment were wrong about Linux `lsof`. They
are not wrong. The audit tested one lsof revision and generalised.

## Command

```
lsof -a -d cwd -F pcn        # == switchboard/live.py:61 CWD_SCAN
```
run as an **unprivileged** user (uid 1000/1001), with foreign root-owned processes present,
then fed through `live._parse`'s exact rules (`live.py:100-113`).

## Result — it depends on the lsof revision, and the newer one breaks

| Image | lsof revision | Group shape | `_parse` |
|---|---|---|---|
| ubuntu:22.04 | 4.93.2 | 4 lines (`p`/`c`/`fcwd`/`n`) | OK |
| debian:11 | 4.93.2 | 4 lines | OK |
| **ubuntu:24.04** | **4.95.0** | **3 lines — no `fcwd`** | **rejects the whole scan** |
| **debian:12** | **4.95.0** | **3 lines** | **rejects the whole scan** |
| macOS host | 4.91 | 4 lines | OK |

At lsof 4.94+ the `f` (file-descriptor) field is only emitted when `-F` *asks* for it.
`-F pcn` does not ask for it. So on Ubuntu 24.04 — the distro `wsl --install` installs by
default — `len(lines) % 4` is non-zero, `_parse` returns `None`, `live.scan()` returns
`None`, and `broker.py:2299-2311` raises *"cannot close …: this machine could not be asked
what is running in …"*. **`sb cleanup` and `sb workspace close` refuse permanently.** Not a
degradation — a hard refusal, by design.

Exit code is **0** in every case above, privileged or not, so the exit-code branch
(`live.py:94`) is not the hazard; the shape check is.

## The fix is one character

Add `f` to the format string: `("lsof", "-a", "-d", "cwd", "-F", "pcnf")`. Verified to
produce the 4-line `p`/`c`/`fcwd`/`n` group `_parse` already expects on **all five** rows
above, including macOS 4.91 and the two 4.95.0 images. (`-F fpcn` behaves identically —
lsof orders the output itself, the string only selects fields.)

## Second, independent Linux difference (confirms the audit's one correct finding)

Unprivileged **Linux** lsof does *not* omit other users' processes the way macOS's does.
It lists them with `n/proc/<pid>/cwd (readlink: Permission denied)`, which starts with
`n/` and so parses into a `Proc` with a nonsense cwd. Harmless to the gate (that string
never matches a real checkout), but `live.py`'s module docstring states the macOS
omission behaviour as if it were universal. It is not.

## What this means for the tracked contradictions

- `tests/test_live.py:70` (skip on non-darwin) and the CI comment at `tests.yml:17-21` are
  **correct as written** for current distros. Do not un-skip.
- `audits/researcher-process-liveness-findings.md`'s headline ("the Linux lsof parse bug
  does not reproduce") is **wrong**, and its recommendation to un-skip that test would have
  turned a documented gap into a red build. Its lsof-revision claim was true only for
  4.93.2 (Ubuntu 22.04 / Debian 11, both superseded).
