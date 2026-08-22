# Mac → PC dev-environment migration — the minimal plan

Written 2026-08-22. Investigation + writing only; nothing was changed. Builds on
`notes/pc-migration-findings.md` (branch `worker-pc-migration-check`) and re-verifies
every item it keeps against this Mac.

**Precondition, stated once and not planned here:** the target is **WSL 2**, not native
Windows, and `sb workspace close` stays broken there until `live._parse` learns the
three-line Linux `lsof -F pcn` shape. Porting that is a separate job.

---

## 1. Migration plan

**The principle.** Copy only what a *fresh session on the PC cannot regenerate and would
behave differently without*. Everything switchboard writes for itself — the store, hook
files, panel and sweep locks, prompt scratch — is regenerated on first use. Everything
agents wrote *about* past work is history, not configuration.

Result: **7 files to copy, 4 path rewrites, 1 repo edit, 3 things to install.** Total
payload well under 100 KB. The 40 MB `.git/agentflow/` store does **not** travel.

**Two agents, in order.**

| | Agent | Job |
| --- | --- | --- |
| 1 | *collect* (on this Mac) | Build the zip from §2, drop `TODO.md` (§3) at its root, hand the zip to the human. Copies files; edits nothing. |
| 2 | *reconfigure* (on the PC, inside WSL 2) | `git clone` the repo, unpack the zip over it, work `TODO.md` top to bottom, finish with `sb doctor`. |

The human moves the zip between them. Neither agent needs the other's machine.

---

## 2. Zip contents

Placeholders the PC agent fills in: `$REPO` = the PC clone's absolute WSL path (e.g.
`/home/andrew/code/switchboard`), `$HOME` = the WSL home.

### Files that are copied

| # | What | Mac source | Lands on PC | Why a fresh session breaks without it |
| --- | --- | --- | --- | --- |
| 1 | Claude Code global settings | `~/.claude/settings.json` | `$HOME/.claude/settings.json` | Holds `autoMode.allow` (the pre-authorised `gh pr`, `sb:*`, `herdr:*` rules), `model`, `effortLevel`, `enabledPlugins`. Without it every unattended agent stalls on a permission prompt. **3 Mac paths inside — see §3.** |
| 2 | Statusline script | `~/.claude/statusline-command.sh` | `$HOME/.claude/statusline-command.sh` | `settings.json` above invokes it by absolute path; copying #1 without this leaves a statusline that errors every render. No paths inside it. |
| 3 | Repo permission grants | `$REPO/.claude/settings.local.json` | `$REPO/.claude/settings.local.json` | Gitignored, 8 allow rules (`git *`, `./bin/sb inbox *`, `herdr agent/pane *`, the python). Without it agents prompt on ordinary repo commands. **1 Mac path inside — see §3.** |
| 4 | Local preset bindings | `$REPO/.switchboard/presets.toml` | same | Gitignored. Its one live line is `[roles] py-qa = ["py-qa"]`. Without it `--role py-qa` spawns with no py-qa preset. |
| 5 | py-qa role | `$REPO/.switchboard/roles/py-qa.md` | same | The role's actual definition. Absent, `--role py-qa` silently falls back to the generic role prompt. |
| 6 | py-qa preset | `$REPO/.switchboard/presets/py-qa.md` | same | The fragment #4 binds. A binding naming a missing file is a broken spawn. |
| 7 | herdr config | `~/.config/herdr/config.toml` | `$HOME/.config/herdr/config.toml` | `onboarding = false`, theme, `[ui.toast] delivery = "herdr"`. Without it herdr re-runs onboarding on first launch and toasts route differently. Verified **path-independent** — copy as-is, no rewrite. |

### Not a file — a repo edit (does NOT go in the zip)

| What | Where | Action |
| --- | --- | --- |
| Hardcoded interpreter in the house rules | `.switchboard-shared/presets/house-rules.md:81` — `/Users/andrew/anaconda3/bin/python` | **Tracked file.** Edit on the PC and commit. Every agent reads this preset on every spawn, so a Mac-only python path is wrong advice given to everything. |

That is the *only* functional hardcoded `/Users/andrew` in tracked code. A full
`git grep` found 14 other hits, all inert: prose in `defaults/roles/dispatcher.md`,
literal string fixtures in `tests/test_accept_teardown.py`, and captured tool output in
`research/modal-captures/*.txt`. Leave them.

### Deliberately excluded — and why

| Excluded | Size | Reason |
| --- | --- | --- |
| `.git/agentflow/state.db` (+ `-shm`, `-wal`) | 37 MB | Operational state only. `store.py:96` calls it "disposable by design", `sb doctor --reset-store` drops and recreates it, and the schema is rebuilt on first use. A fresh session needs no prior agent tree. |
| `.git/agentflow/config.json` | 56 B | Records `main_checkout: /Users/andrew/Code/switchboard`. Do **not** copy a file whose entire content is a wrong path — `sb init` writes it correctly on the PC (`broker.py:1150`). |
| `.git/agentflow/hooks/` | 548 KB, 137 files | Per-agent settings JSON that `hooks.settings_file()` writes itself. |
| `.git/agentflow/{panel,sweep,prompts}/` | 2.4 MB | Locks, a snapshot, and prompt scratch. All regenerated. |
| `.git/agentflow/plugins/plans/`, `todo/` | 300 KB | Plan records p-6…p-28. Finished-plan history, not config. **One judgement call:** if a plan is still *running* and must continue on the PC, that one `p-NN.json` plus `_meta.json` is the exception — run `sb plugin plans list` before zipping and decide then. |
| `.switchboard/roles.toml`, `.switchboard/models.toml` | 4 KB | Verified: **every setting in both is commented out.** They are documentation of shape, not configuration. Nothing changes if they are absent. |
| `.switchboard/{briefs,design,notes,handoffs,tasks}/` + loose `*.md` | ~3 MB, ~200 files | Agent-written history of past work. A fresh session reads none of it. |
| `.switchboard/state.db*` | 90 KB | Stale legacy file — no code in `switchboard/` references this path at all. |
| `~/.local/state/switchboard/plugins/` | 5 files | Filed bug reports and suggestions. The plugin creates the directory on the next file it writes. Nothing reads them at startup. |
| `~/.claude/projects/.../memory/` | — | Out per scope. No code path depends on it. |
| `~/.claude.json`, `~/.claude/projects/*`, `sessions/`, `history.jsonl`, `shell-snapshots/` | ~1 MB+ | Transcripts. Regenerate. |
| `.pytest_cache/`, `__pycache__/`, `.scout-*.md`, `.claude/RESUME.md` | — | Scratch. |
| `$REPO/CLAUDE.md` | — | Gitignored, and **does not exist on this Mac**. Nothing to copy. |
| `$REPO/.claude/settings.json` | — | Tracked. Arrives with the clone. |
| `~/.config/switchboard/models.toml` | — | Does not exist here. |
| GitHub auth | — | Re-done with `gh auth login`. Never copied. |

---

## 3. `TODO.md` outline (ships at the zip root)

Ordered; each step is checkable.

### 0 — Prerequisites (inside WSL 2)

- `python3 -V` → must be **3.11 or 3.12**. 3.13 is excluded from CI on purpose. Mac is on 3.11.5.
- `apt install lsof` — WSL distros do not ship it; `sb`'s liveness scan shells out to it.
- `git`, `gh`, `herdr` on PATH. Claude Code installed.
- Note the known gap: `sb workspace close` will refuse until `live._parse` handles Linux `lsof`.

### 1 — Clone and pin

1. `git clone <origin> $REPO` (origin is HTTPS).
2. `cd $REPO && ./bin/sb init` — writes `.git/agentflow/config.json` with `main_checkout = $REPO`. **Do not hand-write this file.**
3. Verify: `cat .git/agentflow/config.json` shows the PC path, no `/Users/andrew`.

### 2 — Unpack, then rewrite paths

Copy items 1–7 from §2 into place, then make exactly these four edits:

| File | Find | Replace with |
| --- | --- | --- |
| `$HOME/.claude/settings.json` → `statusLine.command` | `bash /Users/andrew/.claude/statusline-command.sh` | `bash $HOME/.claude/statusline-command.sh` |
| `$HOME/.claude/settings.json` → `autoMode.allow[]` | `Bash(sb:*) in /Users/andrew/Code/switchboard` | `Bash(sb:*) in $REPO` |
| `$HOME/.claude/settings.json` → `autoMode.allow[]` | `Bash(herdr:*) in /Users/andrew/Code/switchboard` | `Bash(herdr:*) in $REPO` |
| `$REPO/.claude/settings.local.json` → `permissions.allow[]` | `Bash(/Users/andrew/anaconda3/bin/python *)` | `Bash(<the WSL python3 you resolved in step 0> *)` |

`~/.config/herdr/config.toml` needs **no** rewrite.
Then: `chmod +x $HOME/.claude/statusline-command.sh`.

### 3 — Repo edit (tracked; commit it)

- `.switchboard-shared/presets/house-rules.md:81`: replace `/Users/andrew/anaconda3/bin/python` with the WSL interpreter, and reword "On Andrew's machine" so it reads true on the PC.
- Commit on a branch and open a PR — this is a tracked-file change, so it goes through the normal gate, not straight to `main`.

### 4 — Install and link

- `python3 -m pip install -r requirements.txt` — one optional dep, `rich`. Into the **same** interpreter `bin/sb` resolves to. Without it `sb board` falls back to the plain renderer and loses nothing but polish.
- `mkdir -p $HOME/.local/bin && ln -s $REPO/bin/sb $HOME/.local/bin/sb`; confirm `$HOME/.local/bin` is on PATH. (Mac has exactly this symlink.)
- `chmod +x $REPO/bin/sb $REPO/bin/sb-stop-hook $REPO/bin/sb-activity-hook`.

### 5 — Re-auth

- `gh auth login` — never copied. Verify with `gh auth status` and `gh pr list`.

### 6 — Verify

- `sb doctor` — clean.
- `sb plugin list` — `report-bug`, `suggestions`, `plans` enabled (from tracked `defaults/plugins.toml`; nothing local needed).
- `sb presets house-rules` — prints, and shows the **PC** python path.
- `sb presets py-qa` and a `--role py-qa` spawn — proves items 4–6 landed.
- `python -m pytest tests` — full suite.
- `sb start` a throwaway agent, let it `sb done`, then `sb cleanup` — proves store creation, hooks, and herdr panes end to end.

---

## Unverified / assumptions

- **`rich` version** — importable on the Mac, but `rich.__version__` does not exist so the installed version was not read. `requirements.txt` pins `rich>=13.0`; assume any current release is fine.
- **The PC's WSL python path** — unknown from here; every rewrite above names it as a placeholder the PC agent resolves in step 0.
- **`gh` / origin over HTTPS with an OS-keyring token** — taken as given from the prior report, not re-run here.
- **The statusline script's internals** were not read beyond confirming it contains no `/Users/andrew`. If it shells out to a Mac-only binary, that surfaces on first render, not before.
- **Running plans** — `sb plugin plans list` was not run (it would have been a state read on a live store mid-session). The collect agent must check it before excluding `.git/agentflow/plugins/plans/`.
- **herdr on Windows/WSL** — the prior report's platform verdict is taken as given.
