# Adversarial review — §2 inventory completeness — `notes/windows-support/native-port-plan.md`

*(Path corrected 2026-08-22: this reviewed the **native-port** plan, which then lived at `notes/windows-support-plan.md` and is now `notes/windows-support/native-port-plan.md`. The file at `notes/windows-support-plan.md` today is the WSL2 plan, which this did NOT review.)*

Reviewer: `reviewer-inventory-completene`. Lens: **is the §2 inventory of platform-specific
code paths complete?** Nothing else was reviewed and nothing was changed.

**Verdict: NEEDS CHANGES before Phase 1 starts.** The inventory of the `switchboard/` package
itself is strong — I attacked it hard and found only citation drift there. But it has one
systemic blind spot (the whole `defaults/` tree was never swept by any of the six audits) and
two entries that name 2–3 lines for what is actually a package-wide class of bug.

Method: grepped the whole checkout for the POSIX-API list in the brief; read every hit;
checked CPython 3.11.5's own `subprocess.py` for one claim; decoded the repo's text files as
cp1252 to test the encoding claim rather than assert it. Where I could not verify (no Windows
box) I say so.

---

## Evidence that the blind spot is real, not a guess

```
$ grep -l "defaults/plugins\|plans plugin\|report-bug\|todo plugin" \
    .switchboard/notes/researcher-{process-liveness,locking-terminal,hooks-entrypoints,\
    worktree-filesyste,tui-rendering,herdr-integration}-findings.md
(no output)
```

Zero mentions across all six source audits. `defaults/plugins/` was never seen, not
audited-and-dismissed. §2 inherits that hole exactly.

---

## Findings, ranked

### G1 — `import fcntl` at module scope in the plans plugin. **BLOCKER (for the plans surface)**

`defaults/plugins/plans/__init__.py:379` — `import fcntl`
`defaults/plugins/plans/__init__.py:2869` — `fcntl.flock(fd, fcntl.LOCK_EX)` (the `_minting` id lock)

**Not covered.** B1 enumerates exactly four module-level `import fcntl` sites
(`broker.py:33`, `plugins.py:62`, `panel.py:69`, `sweep.py:44`) and the "shared primitives"
section enumerates exactly five flock sites. This is a fifth import and a sixth lock.

**What breaks.** `plugins._import` (`switchboard/plugins.py:397`) catches `BaseException` and
`load()` turns it into `status="broken"`. So on Windows the plans plugin does not crash `sb` —
it goes quietly dead, and every `sb plugin plans …` command answers "broken: No module named
'fcntl'". The plans plugin is the merge-gate machinery this protocol treats as authoritative
for pushing and merging, so on Windows there is no merge gate at all, reported as a plugin
health line nobody is looking at.

**Why Phase 1 will not catch it.** Phase 1's exit criterion is `import switchboard.*` succeeds
and pytest collects. Plugins are loaded by path through `importlib.util.spec_from_file_location`,
not as `switchboard.*`, and the failure is swallowed. The criterion passes with plans dead.

**Fix implication.** `lockfile.py` must be importable from a plugin. Today the plugin contract
(`sb doctor` polices it) allows a plugin to import only `switchboard.plugins` — see the comment
at `defaults/plugins/report-bug/__init__.py:284-287`. So either `lockfile` is re-exported through
`switchboard.plugins`, or the contract widens. That is a design decision the plan does not
currently know it has to make.

### G2 — The encoding bug is package-wide; F9 scopes it to two lines. **BREAK**

F9 names `board.py:2179` and `output.py:337`. Those are the two `errors="replace"` sites. But
**no** text read in this codebase passes `encoding=`, and on Windows `Path.read_text()` falls
back to `locale.getpreferredencoding(False)` — the ANSI code page, cp1252 on a default install,
not UTF-8 (Python 3.11/3.12; UTF-8 mode only became the default in 3.15).

Verified, not assumed:

```
defaults/protocol.md   192 non-ASCII bytes; cp1252 decode → 'sessions â€” in this repo'
defaults/settings.toml 293 non-ASCII bytes; cp1252 decode → 'one key at a time â€”'
```

Unlisted sites reading those files with no `encoding=`:

| site | what it reads | consequence on Windows |
|---|---|---|
| `config.py:191` (`config.read_text`) | `defaults/protocol.md`, every role `.md`, agent.md | **every agent's spawn prompt is mojibake** |
| `config.py:163` (`read_toml`) | `defaults/settings.toml` + repo settings | any setting *value* with `—`/`’` is corrupted |
| `models.py:213` | the models TOML | same |
| `presets.py:167`, `:220` | preset bodies | mojibake in what `sb presets` pastes |
| `plugins.py:336` | plugin `agent.md` | mojibake into the prompt |
| `config.py:425`, `:453` | front-matter + protocol | same |
| `defaults/plugins/plans/__init__.py:3848` | `open(path, errors="replace")` | the exact F9 pattern, unlisted |

All of these decode *successfully* as cp1252 (I checked — no crash), so this is silent
corruption of the one artefact switchboard exists to produce. F9's own framing ("also a latent
POSIX bug") is right; the scope is ~8× what §2 says.

### G3 — Hook stdin decode. Not in §2 at all. **BREAK (silent)**

`bin/sb-stop-hook:28` and `bin/sb-activity-hook:27` — `hooks.run(sys.stdin.read())`.

`sys.stdin` on Windows decodes a pipe with the ANSI code page and `errors='strict'`. UTF-8
continuation bytes `0x81 0x8D 0x8F 0x90 0x9D` are **undefined** in cp1252, so a hook payload
containing e.g. `●` (UTF-8 `E2 97 8F`) raises `UnicodeDecodeError` before `json.loads` is
reached. Hooks fail open by design (B6's own words), so the Stop gate silently never fires for
that turn and nothing is logged.

F10 covers `sys.stdout.reconfigure` only. The read side of the same problem has no entry.
Fix is the same shape: `sys.stdin.reconfigure(encoding="utf-8")` in the hook entry points —
which also lands naturally in D2's `hooks_entry.py`.

### G4 — V6 is wrong: `start_new_session` is ignored on Windows, not "mapped". **BREAK**

V6 says `panel.py:583 start_new_session=True` is "confirmed harmless (CPython maps it to
`CREATE_NEW_PROCESS_GROUP` on Windows, does not raise). No change."

Checked against CPython 3.11.5 on this machine
(`/Users/andrew/anaconda3/lib/python3.11/subprocess.py:1435-1444`): the Windows
`_execute_child` signature receives it as `unused_start_new_session` and the body never reads
it. It is **silently discarded**. Nothing is mapped; no `creationflags` are set.

Consequence: the collector spawned at `panel.py:576-586` is the repo's single elected collector
and `start_new_session=True` is what detaches it from the renderer that happened to win the
election. On Windows it stays in that renderer's console and process group — a Ctrl-C in that
pane, or closing that console window, takes the whole fleet's collector down with it. Every
panel then goes stale.

So this is a code change (`creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`), not a
verify-only item. It should move out of §2's V list into the F table.

### G5 — Fourth `os.access(X_OK)` site, and one genuinely-unresolvable `"sb"`. **BREAK**

F6 lists three X_OK sites (`board.py:2217`, `collector.py:475`, `broker.py:415`). There is a
fourth: `defaults/plugins/plans/__init__.py:3573` (`_sb()`).

Separately, and worse: `defaults/plugins/report-bug/__init__.py:269` runs
`subprocess.run(["sb", "inspect", …])` — a **bare literal**, no `shutil.which`, no own-checkout
resolution. Windows `CreateProcess` appends only `.exe` when searching PATH and does **not**
consult `PATHEXT`, so under D2's committed-`.cmd`-shim path this never resolves and bug filing
loses its pane-tail attachment.

One correction in the plan's favour, since I checked it: a `.cmd` *full path* does execute
fine through `subprocess.run` (CreateProcess falls back to `cmd.exe` for `.bat`/`.cmd`), and
`shutil.which` does consult `PATHEXT`. So F6's proposed fix ("invoke that path") is sound —
the break is specifically the bare name, not the `.cmd` extension.

### G6 — V2's `os.replace`-under-readers scope is one file; there are four writers. **VERIFY**

V2 spikes `panel.py:250-259` / `:315` only. The same tmp+`os.replace`-with-unlocked-readers
shape is at `defaults/plugins/plans/__init__.py:3336` and `:3211`, and
`defaults/plugins/todo/__init__.py:221`. The plans plugin documents at `:396` that it takes
**no coarse lock** — readers are explicitly unsynchronised — so it is the *worst* case for the
Windows sharing question, not panel.py.

I also note V2 asserts CPython's reader "relies on `FILE_SHARE_DELETE`" with no citation. I
could not confirm that; CPython's Windows `open()` goes through the CRT `_wopen`/`_SH_DENYNO`,
which grants read+write sharing. Whether delete-sharing is granted decides whether
`os.replace` raises `PermissionError` under a concurrent reader. Flagging it as unverified in
both directions — the plan's "very likely fine" is not evidence either.

### G7 — M6 cites a docstring line. **MINOR (citation)**

M6 says "`is_under` case-fold on NTFS (`live.py:82`)". `live.py:82` is inside `scan()`'s
docstring. The actual comparison is `live.py:136`:

```python
return p.parts[:len(r.parts)] == r.parts
```

The finding is real and worth keeping — `PurePath.__eq__` *is* case-insensitive on Windows but
a tuple-of-`.parts` comparison is not, which is exactly the trap. Just re-point the citation,
or an implementer following §2 edits the wrong thing.

### G8 — B5's marker is a second POSIX-ism at the same site. **MINOR**

`broker.py:3348`: `marker = f"sb={bin_dir}/sb"`. B5's fix says "branch the command by pane
shell family", which reads as touching only the `command` string one line above. The marker is
what `wait_output` matches, and it hardcodes both `/` and the extensionless name — a `cmd`
branch that fixes the command and not the marker still times out into `SbUnpinned`.

### G9 — `hooks.py:157/160` writes Claude Code's settings.json with no encoding. **MINOR**

`p.read_text() == body` / `tmp.write_text(body)`. Claude Code reads its settings as UTF-8;
this writes them in the ANSI code page. A checkout path with any non-ASCII character produces
a settings file Claude Code either mis-parses or reads a wrong path out of, and hooks never
fire. F7 covers only the `shlex.quote` at those same lines, not the codec.

---

## What I attacked and could NOT break — the inventory is right about these

Worth saying, because it bounds how much of §2 is in doubt:

- **`status.py` (2663 lines) and `models.py` are clean.** Grepped both for `subprocess`,
  `signal`, `fcntl`, `termios`, `shlex`, absolute paths, `os.*`. `status.py` has zero
  platform-specific code — every `grep` hit for "signal" is the word in prose about
  switchboard's own activity signal. `models.py`'s only hit is the `read_text()` encoding
  issue above. The brief's suspicion about these two is unfounded.
- **`richboard.py` M4 is correctly called inert.** `legacy_windows=False` at `:1106` feeds a
  `Console` used only through `console.capture()` at `:1112`. The plan's "likely inert —
  verify, don't assume" is the right posture.
- **No `os.fork`, `os.setsid`, `os.getpgid`, `os.killpg`, `os.uname`, `resource`, `os.chmod`,
  `stat.S_I*`, `umask`, `AF_UNIX`, `os.mkfifo`, `os.pipe`, `os.dup`, `time.tzset`, `shell=True`,
  or `PurePosixPath` anywhere** in `switchboard/` or `defaults/`. I checked each one from the
  brief's list. The signal surface really is just SIGINT/SIGTERM/SIGHUP/SIGWINCH (B3/B4).
- **`os.pathsep` is used correctly** at `sweep.py:354` and `panel.py:582`. No `:`-joined PATH.
- **The three `split("/")` sites** (`stats.py:428`, `sweep.py:210`, `broker.py:1856`) all split
  git-reported paths, and git reports forward slashes on every OS. Safe.
- **`herdr.write_prompt_file` (`herdr.py:145,147`) already passes `encoding="utf-8"`** — which
  is why the G2 gap is a gap and not the whole codebase.
- **`store.py`'s git path handling is Windows-safe.** `repo_root`/`worktree_root`/`:1458`
  compare `Path(...).resolve()` objects, and `WindowsPath.__eq__` is case-insensitive.
- Only **one** `sys.platform` branch exists in the whole package (`stats.py:501`) and **zero**
  `os.name`. There is no pre-existing platform seam — §2 is right that these all have to be
  built.

---

## How complete is the inventory overall

**A good inventory of `switchboard/` with one systemic blind spot beside it, plus two
mis-scoped entries.**

- For the `switchboard/` package: near-complete. I found G4 (a wrong verdict), G7 and G8
  (citation/scope drift within a listed entry), and G3 (one genuinely missing entry at the
  `bin/` boundary). Nothing else. The six audits did their job inside their scopes.
- For everything else in the repo: **unaudited**. `defaults/plugins/` is ~10k lines of shipped
  code with its own `fcntl`, its own `os.access(X_OK)`, its own `"sb"` invocation, its own
  encoding bug and its own `os.replace` concurrency — and it is not in §2, not in §3's phases,
  and not in §4's test plan. That is the shape of a concern-scoped fan-out where every
  researcher was pointed at `switchboard/`: the blind spot is where the scopes were drawn, not
  inside any of them.
- The other pattern to fix is **line-citation as scope**. F9 and V2 both name the sites one
  audit happened to touch, and an implementer reading §2 as an inventory will believe those are
  the only sites. Both need to be restated as classes with a grep behind them.

Concretely, before Phase 1: sweep `defaults/` the way `switchboard/` was swept; restate F9 and
V2 as package-wide; move V6 to the F table; add the hook-stdin entry; fix the M6 and B5
citations. None of that changes the phase ordering or any of the four decisions.

---

## Unproven

I have no Windows machine. Everything Windows-side here is from documented CPython/Win32
behaviour, except the two things I actually ran on this Mac: the cp1252 decode of the repo's
text files (G2), and reading CPython 3.11.5's own `subprocess.py` (G4). Those two are
verified. The `CreateProcess`/`PATHEXT` claim in G5 and the `FILE_SHARE_DELETE` question in G6
are documentation-level, not run.
