# Moving switchboard development to another machine

Investigation only — nothing was changed. Scoped to this repo and to switchboard's own
state. Everything below was read off this machine on 2026-08-24.

The one thing that decides the shape of the answer: **is the PC Linux or Windows?**
switchboard is POSIX-only in practice — `stats.py` branches on `darwin`/`linux` and shells
out to `ps`, local config travels into worktrees as SYMLINKS (`[paths] linked_config`),
herdr is a native binary talking to a unix socket at `~/.config/herdr/herdr.sock`, and
README §"Scope" states the assumption as "one human, one machine, herdr on the PATH".
On Linux this is a copy-and-reconfigure job. On Windows it is a port, and WSL2 is the
realistic route.

---

## 1. Copy — content that exists only on this machine

| What | Where | Size | Note |
|---|---|---|---|
| Local git commits | `/Users/andrew/Code/switchboard` | — | **73 branches hold commits that are on no remote.** See below. |
| Repo-local config layer | `<repo>/.switchboard/` | 4.1 MB | gitignored by design; the biggest single loss if skipped |
| Untracked briefs | `<repo>/notes/*-brief.md` | ~32 KB | 5 files, none committed |
| Plans + todo plugin state | `<repo>/.git/agentflow/plugins/` | 428 KB | 42 plan JSONs (`p-2` … `p-N`) |
| Bug / suggestion reports | `~/.local/state/switchboard/plugins/` | ~30 KB | 6 bug reports, 5 suggestions; plain markdown, fully portable |
| Claude project memory | `~/.claude/projects/-Users-andrew-Code-switchboard/memory/` | 88 KB | 10 memories + `MEMORY.md` |

### Local-only commits — do this first
`git push --all origin` from `/Users/andrew/Code/switchboard` is the whole fix, and it is
much safer than copying `.git` around. 73 branches carry commits no remote has; the
largest are `board-layout` (13), `agent-handoff-wording` (11), `sb-setup-skill` (10),
`changelist-build` (9), `worker-9` (8), `task-guardrails-build` (7).

Three live worktrees also hold uncommitted edits that a push will not carry —
`design-truth-citations` (2), `herdr-cleanup-gaps` (2), `citation-checker` (1),
`split-scout` (1). Commit or discard them deliberately before the move.

### `.switchboard/` — what is actually in it
- `briefs/` (1.5 MB, ~210 dirs) — the delegation briefs agents were spawned from
- `notes/` (1.4 MB, ~108 files) — agent working notes
- `design/` (932 KB, ~56 files) — design docs the code cites by path (e.g. `board.py`
  references `.switchboard/design/status-truth.md`)
- `tasks/`, `handoffs/`
- `roles.toml`, `presets.toml`, `models.toml` — all three are commentary with nothing
  overridden, so they are re-creatable, but `roles/py-qa.md` + `presets/py-qa.md` are a
  real local role definition and would be lost
- ~174 files inside mention `/Users/andrew/...` — prose references, harmless, but they
  will read as stale paths on the new machine

### Claude project memory has a path-keyed name
Claude Code keys its per-project directory on a slug of the absolute repo path. Put the
repo at a different path on the PC and the memories land under a new slug and are not
found. Copy the `memory/` directory into whatever
`~/.claude/projects/<slug-of-new-path>/memory/` turns out to be.

---

## 2. Reconfigure fresh — quick, and copying is worse than redoing

- **herdr** — 18 MB native binary at `~/.local/bin/herdr`, version 0.8.0, pinned as the
  minimum by `scripts/00-preflight.sh`. Not in this repo, and no install route is
  documented anywhere in it. Get the same version onto the PC; `scripts/00-preflight.sh`
  is the check.
- **`herdr integration install claude`** — per machine, called out in the preflight.
- **`sb` on PATH** — `~/.local/bin/sb` is a symlink to
  `/Users/andrew/Code/switchboard/bin/sb`. Recreate it pointing at the new checkout path.
- **`sb init`** in the new main checkout — writes `main_checkout` into
  `.git/agentflow/config.json` (currently the absolute `/Users/andrew/Code/switchboard`)
  and re-adds `CLAUDE.md` / `.switchboard` to `.git/info/exclude`.
- **Python deps** — no packaging file; `bin/sb` runs the checkout in place under whatever
  `python3` resolves to. `pip install -r requirements.txt -r requirements-dev.txt` into
  **that same interpreter**. (`rich` is optional; `pytest` + `pytest-xdist` are required
  because `pytest.ini` sets `-n auto`.) On this machine the suite is run with
  `/Users/andrew/anaconda3/bin/python` (3.11.5) — the PATH `python3` is 3.9.6.
- **`gh` CLI + auth** — `gh auth login`. The current token is in the macOS keyring with
  scopes `repo, workflow, read:org, gist, admin:public_key`; keyring entries do not move.
- **Claude Code CLI + login** — currently 2.1.243 at `~/.local/bin/claude`.
- **`codex` CLI** — only if the codex provider is wanted. `~/.codex/auth.json` is a live
  credential; re-login rather than copy.
- **`~/.config/switchboard/models.toml`** — does not exist here; nothing to move.
- **Repo `.claude/settings.local.json`** — permission grants, gitignored, machine-local
  and full of `/Users/andrew` paths. Rewrite rather than copy. (`.claude/settings.json` is
  committed and travels with the clone.)
- **The two convenience symlinks** in the main checkout, `bugs` and `suggestions`, both
  pointing into `~/.local/state/switchboard/plugins/`.

Nothing needs registering in `~/.claude/settings.json`: switchboard injects
`bin/sb-activity-hook` and `bin/sb-stop-hook` per spawn (`hooks.py:207`), not globally.

---

## 3. Do not copy — machine-bound, or worthless off this machine

- **`.git/agentflow/state.db`** (43 MB + a 5 MB WAL) — the live fleet state. Every one of
  its 877 agent rows carries `cwd`, `session_id`, `workspace_id`, `terminal_id`,
  `pane_id`: absolute paths and herdr/Claude handles that mean nothing on another machine.
  Restoring it would give the PC a board full of agents that cannot be reached. Let the
  new machine make its own. (Keep the old one on disk if the 1,610 messages and 104k
  events have archival value — but as an archive, not as state.)
- **`.git/agentflow/codex-homes/`** — 613 MB of per-agent codex homes for finished agents.
- **`.git/agentflow/hooks/`, `panel/`, `prompts/`, `sweep/`, `fork.lock`** — per-turn and
  per-pane scratch tied to live sessions.
- **`~/.config/herdr/`** — `herdr.sock` and `herdr-client.sock` are unix sockets;
  `session.json` is this machine's live pane/tab layout; the two `.log` files are 1 MB of
  local history. Only `config.toml` (7 lines: theme dracula, onboarding off, two UI
  prefs) is worth retyping.
- **`.switchboard/state.db`** (57 KB, last written 9 Aug) — legacy. `store.py:92` puts the
  store at `<git-common-dir>/agentflow/state.db`; nothing reads this one.
- **`~/.claude/projects/-Users-andrew-*switchboard*/` transcripts** — 51 MB for the main
  checkout plus a directory per worktree, all keyed on absolute paths. Agent transcripts,
  not state; switchboard never reads them back.
- **`~/.herdr/worktrees/switchboard/`** — 12 live agent worktrees. Recreated by herdr on
  demand; and the git worktree registrations inside `.git/worktrees/` point at absolute
  `/Users/andrew/.herdr/...` paths, so a copied `.git` arrives with a dozen stale
  registrations needing `git worktree prune`. A fresh `git clone` avoids this entirely,
  which is the argument for pushing branches rather than copying the repo directory.
- **`~/.codex/auth.json`**, the `gh` keyring token, and any SSH keys — credentials. The
  repo remote is HTTPS (`https://github.com/Andrew3019/switchboard.git`), so no SSH key is
  needed for this repo at all.
- **`__pycache__/`, `.pytest_cache/`, `.DS_Store`, `.scout-*.md`, `.claude/RESUME.md`** —
  scratch.

---

## Suggested order

1. `git push --all origin` from the main checkout; commit or discard the four dirty
   worktrees first.
2. Tar up `.switchboard/`, `notes/*-brief.md`, `.git/agentflow/plugins/`,
   `~/.local/state/switchboard/plugins/`, and the Claude memory directory. ~6 MB total.
3. On the PC: install herdr 0.8.0, `herdr integration install claude`, Claude Code, `gh
   auth login`, python deps.
4. `git clone` fresh, drop the tarball's contents into place, symlink `sb`, `sb init`.
5. `scripts/00-preflight.sh`, then `sb doctor`, then `python -m pytest tests`.

## Not verified

None of this was executed on a second machine — it is read off configuration, code and
disk here. In particular the herdr install route is undocumented in this repo, and
whether herdr 0.8.0 exists for the PC's OS at all is unknown from here.
