# Moving development to a Windows PC — findings

Investigation only, 2026-08-22. No code changed. Two questions: does switchboard + Claude
Code run on Windows, and what on this Mac is not in git.

## 1. Platform support

### Claude Code — fine, with one caveat
Officially supported on Windows 10 1809+ / Server 2019+, natively (PowerShell/CMD, WinGet
or the `install.ps1` installer) or under WSL 2. Git for Windows is recommended natively so
the Bash tool works; without it Claude Code falls back to the PowerShell tool.
**Sandboxing is not supported on native Windows** — only WSL 2. Source:
https://code.claude.com/docs/en/setup

### herdr — fine
`herdr` ships native Windows support: the binary carries ConPTY handling, a
`cmd.exe /d /c` command path, a `WindowsConsole` key source, and its own config notes say
the update channel "defaults to `stable` on Linux/macOS and `preview` on Windows". Nothing
here needs replacing. (Pinned version on this machine: herdr 0.8.0, protocol 19.)

### switchboard — does NOT run on native Windows today
Hard blockers, all in the import path of the core:

| File | What | Why it breaks |
| --- | --- | --- |
| `switchboard/broker.py:33` | `import fcntl` | module does not exist on Windows |
| `switchboard/plugins.py:62` | `import fcntl` | same |
| `switchboard/panel.py:69` | `import fcntl` | same |
| `switchboard/sweep.py:44` | `import fcntl` | same |
| `switchboard/board.py:55` | `import termios` | same |

These are module-level imports in `broker.py` — the module every `sb` verb goes through —
so `sb` does not start at all, not merely degrade. The locking itself is four `flock`
call sites (`plugins.py:687`, `sweep.py:308`, `broker.py:2863`, `panel.py:435/474`) and
one raw-mode `tcgetattr/tcsetattr` pair (`board.py:2395`); a port is small in volume, but
it is a port.

Beyond the imports:

- **POSIX-only subprocesses.** `lsof` (`live.py:61`), `ps -Ao` (`stats.py:438`,
  `broker.py:2464`), `vm_stat` (`stats.py`). None exist on Windows.
- **Hook scripts.** `hooks.py` writes hook commands as a bare path to
  `bin/sb-stop-hook` / `bin/sb-activity-hook`, quoted with `shlex.quote`. Both rely on a
  `#!/usr/bin/env python3` shebang and POSIX shell quoting. Neither survives cmd.exe.
- **Worktree symlinks.** Every worktree gets a symlink for `CLAUDE.md` and `.switchboard`
  (`broker.py:1116`, `paths.linked_config`). On native Windows `Path.symlink_to` needs
  Developer Mode or admin.
- **No cross-platform testing, stated.** CI matrix is `ubuntu-latest` + `macos-latest`
  only (`.github/workflows/tests.yml`); the README's Status section says outright: "it
  assumes one human, one machine, herdr on the PATH… no packaging story, no cross-platform
  testing".

### WSL 2 — the realistic route, but one known gap
Linux is a supported target for Claude Code and herdr, and `fcntl`/`termios`/`ps` all
exist, so switchboard *imports and runs*. One documented Linux defect matters:

- **`sb workspace close` would refuse forever.** `live.CWD_SCAN` parses `lsof -F pcn`
  output in its BSD four-line shape; Linux emits three lines and `_parse` rejects every
  group, so `live.scan()` answers "cannot tell" for everything. The close gate is
  deliberately fail-safe (`broker.py:2305`): `found is None` raises *"this machine could
  not be asked what is running… nothing is closed and nothing is deleted"*. So on WSL,
  closing a workspace is impossible until the parser learns the Linux shape. This is
  written down already, in `tests/test_live.py:76` — the test is skipped on Linux with a
  note saying "Linux support would start with the parser".
- Also needs `lsof` installed (`apt install lsof`), which WSL distros do not ship by
  default.
- `stats.py` already has a `_available_linux()` path, so memory/CPU are fine.

**Recommendation: WSL 2, plus the `live._parse` Linux fix.** Native Windows is a genuine
port (five modules, hooks, symlinks, three shelled-out POSIX tools) with no test coverage
behind it.

## 2. What is on this Mac and not in git

### Must copy — nothing else can reproduce it
| What | Where | Size / note |
| --- | --- | --- |
| The switchboard STORE | `<repo>/.git/agentflow/` | 40 MB. Inside `.git`, so a clone does not get it. Holds `state.db` (agents, messages, parent links), `config.json`, per-repo plugin state, prompts, hook settings. |
| Plans plugin state | `.git/agentflow/plugins/plans/` (p-6 … p-28) | 296 KB. Every running and finished plan. |
| Todo plugin state | `.git/agentflow/plugins/todo/` | small |
| Local repo config | `<repo>/.switchboard/` | 3.1 MB — gitignored. `roles.toml`, `models.toml`, `presets.toml`, plus ~200 briefs/design/handoff notes agents wrote. |
| Machine-wide plugin state | `~/.local/state/switchboard/plugins/` | filed bug reports and suggestions (5 files). The sibling `switchboard.db` is empty. |
| Uncommitted briefs | `notes/board-layout-brief.md`, `notes/task-guardrails-brief.md`, `-build-brief.md`, `-plan-brief.md` | untracked in the main checkout right now — commit them before migrating, or they are lost |
| Claude Code permission grants | `<repo>/.claude/settings.local.json` | gitignored; 8 allow rules |
| Claude Code global settings | `~/.claude/settings.json` | model, statusline, `autoMode.allow` (incl. the pre-authorised `gh pr` rules), enabled plugins, voice |
| Claude Code auto-memory | `~/.claude/projects/-Users-andrew-Code-switchboard/memory/` | **path-keyed**: the directory name is derived from the repo's absolute path, so it must be renamed to the PC's path or the memories are invisible |
| herdr config | `~/.config/herdr/config.toml` | theme, sidebar, toast delivery, onboarding=false |

Notes on paths that will be wrong on the PC:
- `.git/agentflow/config.json` records `main_checkout: /Users/andrew/Code/switchboard` — must be
  rewritten to the PC path.
- `~/.local/bin/sb` is a symlink to `<main checkout>/bin/sb`; the PC needs its own
  equivalent on PATH.
- `.switchboard-shared/presets/house-rules.md:81` hardcodes
  `/Users/andrew/anaconda3/bin/python`. That one is *tracked* — it is a repo edit on the
  PC, not a copy.

### Do not copy — re-do on the PC
- **GitHub auth.** `gh auth status` shows an OS-keyring token, and `origin` is HTTPS.
  Just `gh auth login` on the PC. SSH keys in `~/.ssh` are not used by this repo's remote.
- **`~/.claude.json`** (850 KB) — session/project history, regenerates.
- **herdr worktrees** under `~/.herdr/worktrees/` — recreated by `sb workspace`.
- **`~/.claude/projects/`, `sessions/`, `history.jsonl`, `shell-snapshots/`** — transcripts and
  caches. Copy only if the session history matters.
- **`.pytest_cache/`, `__pycache__/`, `.scout-*.md`, `.claude/RESUME.md`** — scratch.

### Environment
- No env vars are required. The optional ones switchboard reads are `SB_DEBUG`,
  `SWITCHBOARD_DEFAULTS`, `SWITCHBOARD_MODELS_CONFIG`, `NO_COLOR`; `HERDR_PANE_ID` and
  `HERDR_WORKSPACE_ID` are set by herdr itself.
- `~/.config/switchboard/models.toml` (the per-user tier override) does not exist here —
  nothing to copy.
- Only third-party dependency is `rich`, and it is optional (`requirements.txt`).
- Python 3.11 or 3.12 (3.13 is deliberately excluded from CI, see the workflow comment).
