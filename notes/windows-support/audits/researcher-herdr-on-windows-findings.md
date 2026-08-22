# herdr on Windows: H1 + H2 findings

Source: local clone `/Users/andrew/Code/herdr` (read-only), commit tip as checked out
during this research. All citations are `file:line` in that repo unless noted.

## H1 — Does herdr natively run on Windows and open an agent pane?

**Verdict: qualified yes — real, shipped, CI-tested, but explicitly "experimental beta,"
not "stable."** Confidence: high (based on direct reading of CI config, release docs,
and the actual ConPTY spawn code — not on herdr's marketing copy alone).

### It's a real, tested target, not just "compiles on Windows"

- `Cargo.toml:44-63` — `[target.'cfg(windows)'.dependencies]` pulls in `windows-sys`,
  `wmi`, `widestring`; `portable-pty = "=0.9.0"` is patched to the vendored copy at
  `vendor/portable-pty` (`Cargo.toml:33-34`).
- `.github/workflows/ci.yml:44-56` — the `check` job matrix runs on `windows-latest`
  (alongside ubuntu/macos) on every PR and push to `master`/`windows`, running
  `scripts/windows_check.ps1 -Mode check` (build + clippy + fmt on the Windows target).
- `.github/workflows/ci.yml:117-124` — a **"Smoke ConPTY pane"** step runs
  `scripts/windows_smoke_conpty_path.ps1` against the built `herdr.exe`, i.e. CI actually
  opens a ConPTY pane end-to-end on Windows, not just compiles.
- `.github/workflows/ci.yml:126-201` — a separate `windows-conpty-package` job (on
  `windows-2022`) builds the app-local ConPTY package, verifies a tampered bundle is
  rejected, verifies the `HERDR_WINDOWS_CONPTY=system` override works, and runs an
  "enhanced pane input" probe plus a packaged-installer test. This is meaningfully
  thorough CI, not a token build.

### But it is NOT in the automatic stable release pipeline

- `.github/workflows/release.yml:42-63` — the tag-triggered release build matrix only
  has `x86_64/aarch64-unknown-linux-musl` and `x86_64/aarch64-apple-darwin`. **No Windows
  target.** Stable `vX.Y.Z` tags do not produce a Windows binary.
- `.github/workflows/build-artifacts-manual.yml:191-247` — Windows binaries are only
  built by a separate manual/`workflow_dispatch` job (`build-windows`, gated on
  `inputs.build_group == 'windows' || 'all'`), producing a zip with the bundled ConPTY
  package.
- `docs/next/website/src/content/docs/install.mdx:6` — "Herdr ships stable binaries for
  Linux and macOS. **Native Windows support is preview-only beta.**"
- `docs/next/website/src/content/docs/install.mdx:93-99,139,153` — Windows binaries are
  published only on preview GitHub prereleases; `herdr channel set stable` is rejected on
  Windows until a stable Windows release exists.
- `docs/next/website/src/content/docs/windows-beta.mdx:1-10` — dedicated doc titled
  "Windows beta": "Native Windows support is experimental beta... This preview is not a
  commitment that every Linux/macOS feature will become fully supported on Windows."
  Explicitly framed as a feedback-gathering beta that could stay beta or be reduced.

### Pane-creation path on Windows is real, not stubbed

- `vendor/portable-pty/src/win/psuedocon.rs:40-79,306` — loads `CreatePseudoConsole` via
  `kernel32` at runtime and calls it directly (`(CONPTY.CreatePseudoConsole)(...)` at
  line 306). This is a genuine ConPTY implementation, not a feature-flagged stub.
- `src/pane.rs:1494-1499` — `is_powershell_shell()` and related helpers show live logic
  that special-cases PowerShell-launched Windows panes for shell-mode / login-shell
  handling, i.e. downstream pane code actively branches on "this is a real Windows pane."
- `.github/workflows/release.yml`-style CI smoke test (cited above) proves it spawns a
  real child process through ConPTY at test time, not just that the code paths exist.

### Default shell on Windows: **PowerShell, not `cmd.exe`**

This directly contradicts the prior migration note's claim.

- `src/pane.rs:1318-1320` — `fn default_pane_shell() -> String { "powershell.exe".into() }`
  under `#[cfg(windows)]`. The non-Windows branch (`src/pane.rs:1322-1324`) defaults to
  `/bin/sh`.
- `src/pane.rs:1298-1315` — `pane_shell_from()` resolution order: explicit
  `default_shell` config value wins; only if unset does Windows fall through to
  `default_pane_shell()` (PowerShell) — Unix instead falls through to `$SHELL`, then
  `/bin/sh`.
- `docs/next/website/src/content/docs/configuration.mdx:62` — confirms in prose: "When
  unset or empty, Herdr uses `$SHELL`, then `/bin/sh` on Unix and **PowerShell on
  Windows**."
- `cmd.exe` does appear, but only for a different purpose: **custom command strings**
  (keybindings, plugin commands) are run through `cmd.exe /d /c` on Windows
  (`configuration.mdx:62,216`; `src/plugin_command.rs:43` reads `ComSpec`, defaulting to
  `C:\Windows\System32\cmd.exe`). That's the shell used to execute one-off command
  strings, not the shell a normal interactive pane opens into.
- `windows-beta.mdx:29` lists "`cmd.exe` panes" as a supported-in-beta capability
  separately from the default PowerShell pane, meaning `cmd.exe` panes exist but are not
  the default — a user/config has to ask for one (e.g. `default_shell = "cmd.exe"`, or a
  pane opened with an explicit `command = "cmd.exe"` per `configuration.mdx:194`).

### Windows-specific caveats herdr's own docs flag

- IME: `configuration.mdx:460-461` — "Windows support is currently limited to the Korean
  IME" for the ASCII-input-source-switch feature; other IME languages are unaffected by
  that setting.
- Cursor rendering: `troubleshooting.mdx:17` and `windows-beta.mdx:67-78` — native
  Windows cursor can flicker/jump during ConPTY repaint; herdr defaults to a drawn
  (non-native) cursor on Windows/WSL, trading off IME candidate-window anchoring.
- Remote: `windows-beta.mdx:92-97`, `persistence-remote.mdx:66-68` — Windows is
  supported only as a **local client** attaching to Linux/macOS remote hosts; **Windows
  is not supported as a `herdr --remote` target host**; direct terminal attach is
  Unix-only in the beta; Windows OpenSSH doesn't get herdr's control-socket connection
  reuse.
- ConPTY runtime: `windows-beta.mdx:84` — preview packages bundle Microsoft's app-local
  ConPTY runtime because system ConPTY on older Windows 10 builds drops Kitty keyboard
  protocol sequences some agents need; `HERDR_WINDOWS_CONPTY=system` is an opt-out for
  diagnosis only.
- Plugins: `windows-beta.mdx:44` — plugin platform support on Windows is "preview" /
  "best effort"; Unix-only command strings (`sh`, Bash) need Windows-specific
  alternatives.
- No explicit minimum Windows version or Developer Mode / symlink note was found in the
  docs I read — `windows-beta.mdx` and `install.mdx` don't call one out. Not found ≠
  doesn't exist; I did not find a requirements/prerequisites section stating a minimum
  Windows build number.

### What remains unprovable without a real Windows box

- I did not run herdr on Windows myself; this is 100% source/doc/CI-config reading.
  Everything above about "CI actually spawns a pane" is based on reading the workflow
  YAML and the scripts it invokes, not on watching a live Windows runner execute.
- Real-world reliability, the "partial support" table entries (e.g. "Live cwd after
  shell `cd`" listed as `partial` at `windows-beta.mdx` — table continues past what I
  quoted above), and actual user-reported bug volume aren't assessable from source alone.

---

## H2 — Does herdr's API/CLI report a pane's shell family?

**Verdict: no.** Confidence: high — checked every pane/tab/workspace schema struct and
the socket-api doc's method table; none carry a shell or OS/platform field for a pane.

### Nothing in the schema reports it

- `src/api/schema/panes.rs` — `PaneInfo` (fields dumped lines ~400-430: `terminal_id`,
  `workspace_id`, `tab_id`, `cwd`, `foreground_cwd`, `label`, `agent`, `title`,
  `agent_status`, `scroll`, `revision`, etc.) has **no shell/platform field**.
- `src/api/schema/panes.rs:438-449` — `PaneProcessInfo` (returned by `pane.process_info`,
  the verb behind switchboard's readiness checks) has `pane_id`, `shell_pid`,
  `foreground_process_group_id`, `tty`, `foreground_processes: Vec<PaneProcessInfoProcess>`.
  `shell_pid` is a bare number — no shell *name* alongside it. `foreground_processes`
  entries (`panes.rs:451-458`) do carry `name`/`argv0`/`argv`, but that's the **foreground
  job** (e.g. the agent CLI running in the pane), not necessarily the shell process
  itself — when the pane is idle at a shell prompt this may or may not resolve to the
  shell binary, and nothing in the schema labels it as "this is the shell."
- `docs/next/website/src/content/docs/socket-api.mdx:198-200` confirms in prose:
  "`pane.process_info` returns the pane's shell pid, foreground process group id... and
  foreground processes with pid, name, argv/cmdline, and cwd when the platform exposes
  them" — no mention of shell name/family anywhere in the doc's method table
  (`socket-api.mdx:104-113`, full verb list) or elsewhere in that file.
- `src/api/schema/tabs.rs:8-19` (`TabCreateParams`), `src/api/schema/worktrees.rs:12-27`
  (`WorktreeCreateParams`), `src/api/schema/workspaces.rs:8-17`
  (`WorkspaceCreateParams`) — none of the pane/tab/workspace-creation params structs
  accept a shell override either. Fields are limited to `workspace_id`, `cwd`, `branch`,
  `base`, `path`, `label`, `env`, `focus`.
- Cross-referenced against switchboard's own `switchboard/herdr.py` in this worktree: the
  verbs it actually calls (`tab create`, `pane split`, `pane list`, `pane run`,
  `send-keys`, `pane read`, `pane report-agent(-session)`, `pane release-agent`,
  `worktree create/open`, `workspace create`) match exactly the verb set above — none of
  switchboard's own call sites are reaching a verb that would carry shell info either.

### Fallback switchboard would have to rely on

Since herdr doesn't report per-pane shell family, and doesn't accept a shell override at
pane/tab/worktree/workspace creation time, switchboard's only lever is herdr's **global,
config-level default shell**:

- `src/pane.rs:1298-1324` — absent an explicit `default_shell` config value, herdr always
  launches `powershell.exe` on Windows and `$SHELL`/`/bin/sh` on Unix. That's a
  per-*install*, not per-*pane*, fact.
- So switchboard can infer shell family only by knowing **which OS the herdr instance it's
  talking to is running on** (which it already knows — it's the one launching/talking to
  that herdr process) **plus** whatever `default_shell` switchboard itself configured (or
  left unset) in that herdr instance's `config.toml`. If switchboard doesn't control that
  config file, it must additionally assume herdr's shipped default (PowerShell) unless it
  has reason to believe the user customized `default_shell`.
- There is no way to ask "what shell does pane X actually have" after the fact through
  the API — switchboard would be trusting its own assumption about the config, not a
  verified runtime fact from herdr.

### Can switchboard force a shell at pane-creation time to sidestep detection?

**Not through the socket API/CLI creation verbs.** The only shell-selection knobs found
are:
1. Herdr's own `config.toml` `default_shell` (`configuration.mdx:59`) — process-wide,
   not settable per API call.
2. A per-keybinding/custom-command `command = "..."` string
   (`configuration.mdx:194,216`) — that's for keybinding-triggered one-off commands, not
   for choosing the shell of a newly created interactive pane via `tab.create` /
   `pane.split` / `worktree.create`.

So switchboard cannot pass e.g. `{"shell": "cmd.exe"}` into `tab.create` — that field
doesn't exist in `TabCreateParams`. If switchboard needs a guaranteed shell family, it
would need to pre-configure herdr's `config.toml` before spawning the pane, not do it
per-call.
