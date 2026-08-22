# Adversarial review — phase ordering / dependency correctness (§3) + testability honesty (§4)

Artifact: `notes/windows-support/native-port-plan.md` @ `lead-windows-support-plan`.
*(Path corrected 2026-08-22: this reviewed the **native-port** plan, which then lived at `notes/windows-support-plan.md` and is now `notes/windows-support/native-port-plan.md`. The file at `notes/windows-support-plan.md` today is the WSL2 plan, which this did NOT review.)*
Lens only. Everything below verified against real files in this worktree; commands shown.

**Verdict: the phase *ordering* is sound; the *exit criteria* and the CI/testability claims are
not. Needs changes before implementation starts.** No phase's code needs a later phase's code —
the 1→2→3→3b→4→5→6 graph holds. Every defect I found is in what the gates *check*, and in an
environment dependency the plan never names.

---

## 1. HIGH — herdr-on-Windows is assumed by four phases and established nowhere

`switchboard/herdr.py:1-11`: herdr is an external binary, **pinned to 0.8.0 / protocol 19**, and
it is the only thing that makes a pane. Phases 3 (spawn), 3b (collector detachment), 6 (board in
a pane) and V3/V5 all presuppose it runs natively on Windows and creates Windows panes.

The plan never asks the question. It is not a D-item (D1–D5), not a V-item (V1–V5), and not in
§5's list of what is unproven — which is itself a testability-honesty failure, because it is the
single largest unproven Windows claim in the document.

Consequence if the answer is no: Phases 1, 2, 4, 5 all land and pass their gates, and switchboard
still spawns nothing on Windows. That is the plan's own failure mode — a green check over a dead
subsystem — at plan scale.

**Fix:** make it Phase 0, ahead of D5. "Does herdr 0.8.0 have a native Windows build, and does
`agent start` create a pane there?" gates Phases 3, 3b, 6, 7.

## 2. HIGH — Phase 4 (psutil) turns the existing macOS/Linux legs red, and silently kills the collector

`.github/workflows/tests.yml` (read in full):
- install step is `python -m pip install --upgrade pip pytest` — nothing else;
- run step is `python -m pytest tests` — **no `pip install -e .`**;
- its header comment states the premise out loud: *"switchboard has no dependencies beyond the
  standard library — no requirements.txt, no pyproject.toml, nothing to install but the test runner."*

D1 makes `psutil` a **required** dep and Phase 4 repoints `live.scan`, `stats` and
`broker._parents` at it. `tests/test_live.py` and `tests/test_stats.py` import those modules. The
moment Phase 4 lands, **every existing ubuntu and macOS leg fails at import**. §4's "additive —
no risk to existing legs" was written about adding an OS to the matrix; it does not cover the two
dependency changes Phases 2 and 4 make to the same file. No phase owns that CI edit.

Worse, off CI. `switchboard/panel.py:578-587` spawns the elected collector as
`[sys.executable, "-m", "switchboard.collector"]` with `stderr=subprocess.DEVNULL`. Anyone running
from a checkout via `bin/sb` under an interpreter that lacks psutil gets an ImportError into
`/dev/null`: the collector never comes up, the panel just goes stale. That is B7's exact shape —
a swallowed import error — reintroduced on macOS by Phase 4.

Phase 4's exit criterion ("CPU/mem stats populate") is green on the one dev box that happens to
have psutil installed. Note `stats.py:497-499` rejected psutil for precisely this reason: *"a
dependency the collector's interpreter is not promised."*

**Fix:** Phase 4 must depend on the dep being *installed*, not merely *declared* by Phase 2's
pyproject — plus a CI install-step change, plus an explicit `procscan` import failure that is
loud rather than a DEVNULL'd collector death.

## 3. HIGH — Phase 1's exit criterion is unsatisfiable as written, and the counting bug it exists to prevent survives in the same phase

**(a) "`sb plugin list` reports every shipped plugin `ok`" is false on a healthy macOS today.**
Ran `./bin/sb plugin list` in this worktree:

```
  plans         1.0.0   ok            [enabled, @plans bound to every agent]
  report-bug    1.0.0   ok            [enabled, ...]
  suggestions   1.0.0   ok            [enabled, ...]
  todo          1.0.0   not enabled   [not enabled]
```

`plugins.load` sets `status = "ok" if is_enabled else "not enabled"` (`switchboard/plugins.py:425-426`)
and `defaults/plugins.toml:61` ships `enabled = ["report-bug", "suggestions", "plans"]` — todo is
deliberately OFF. An implementer meeting a gate that cannot go green loosens it ad hoc, and the
loosening is where B7 gets lost again.

Correct criterion: **"no shipped plugin reports `broken`"**. (Verified this still catches B7: a
broken import overrides the not-enabled status — `plugins.py:429` sets `status="broken"` even for
a disabled plugin, and `load_all` imports regardless of enablement, `plugins.py:488-492`.)

Also: `_plugin_list` returns `0` unconditionally (`switchboard/cli.py:1411`). A CI gate must grep
the output; the exit code proves nothing.

**(b) Phase 1 still carries the stale fcntl count that §2 warns about.** Phase 1 body: *"convert
the 6 fcntl sites — 5 in `switchboard/` (B1) and the plans plugin's (B7)"*. Measured:

```
grep -rn "import fcntl" switchboard/ defaults/   → 5 (broker:33, plugins:62, panel:69, sweep:44, plans:379)
grep -rn "fcntl.flock" switchboard/ defaults/    → 8 calls (plugins:687, sweep:308,
      panel:435, panel:453, panel:474, panel:478, broker:2863, plans:2869)
```

So `switchboard/` has **4** imports and **7** calls — neither is 5, and nothing is 6. §2's B1 row
and the `lockfile.py` primitive section both get this right (8 calls, `panel.py:478` named) and
the B1 row even spells out the hazard in prose: *"an earlier draft said 6 while listing 7 and
missing `panel.py:478` … converting all but one leaves `import fcntl` at `panel.py:69`."* §3 is
the text an implementer follows, and it still says 6/5. Following Phase 1 literally leaves
`import fcntl` alive and Phase 1's first exit criterion failing.

## 4. MEDIUM-HIGH — Phase 2's exit criteria are not reachable inside Phase 2

Both halves:
- **"`sb --help` runs on Windows."** Generating `sb.exe` from D2's `[project.scripts]` needs
  `pip install -e .`. `tests.yml` has no install step and its header comment asserts there is
  nothing to install. So this is not CI-provable without a workflow change Phase 2 never
  schedules. (The committed `.cmd` shim path *is* runnable without install — but see finding 12.)
- **"a registered Stop hook actually fires (V4)."** Needs a real Claude Code install on native
  Windows. §4's own "cannot be pinned in CI" list contains *"Claude Code's hook runner"*, and
  Phase 7 is where V1–V5 get run. Phase 2's gate therefore depends on Phase 7 work.

This is the concrete place where the "Phases 1–5 are largely CI-verifiable, Phase 6 is hands-on"
split fails: Phase 2 needs the real box too.

## 5. MEDIUM — Phase 5's criterion tests only the path Andrew will not use, and CI can't reach it either

Criterion: *"a fresh worktree on an **unprivileged** Windows box has working `.switchboard` +
`CLAUDE.md`."* D4 decided the **primary** path is Developer Mode + real symlinks with
`target_is_directory`. The criterion exercises only the junction/copy **fallback** — the branch
D4 explicitly says does not apply to Andrew's machine. The path he actually runs has no gate.

Nor is the fallback CI-reachable: GitHub `windows-latest` runners run elevated, so `os.symlink`
succeeds and the fallback branch never executes. Only §4's mocked `OSError(1314)` unit test covers
it — which is fine, but it means Phase 5 is *not* "largely CI-verifiable" in the sense claimed.

And "working" is too weak for M5: if the symlink path is taken, the two `is_symlink()` sites
(`broker.py:1113`, `:1856`) are never asked the junction/copy question, so the criterion goes
green with M5 unfixed.

**Fix:** two criteria — one for the symlink path (link created, `target_is_directory` correct,
both detection sites classify it as ours) and one for the fallback path.

## 6. MEDIUM — Phase 4's criteria are green over the exact failures D1 costs 3 and 5 predict

- *"CPU/mem stats populate."* D1 cost 3 says a stateless `procscan` reads **`0.0` forever**.
  `0.0` is a populated number. The gate must be §4's own test wording — **non-zero across two
  consecutive collector samples** — not "populate".
- *"`sb workspace close` gate answers correctly."* D1 cost 5's empty-cwd trap makes the gate
  **refuse forever**, and refusal is the fail-safe (`broker.py:2305`). A check that only confirms
  "refuses while an agent is live" is green over a permanently-dead gate. The gate needs the
  positive case: **an empty workspace actually closes.**

Both are the plan's signature failure mode, in the plan's own criteria. The §4 test list already
has the right wording for both; §3 does not inherit it.

## 7. MEDIUM — F11 is scheduled in Phase 1 but its fix lives in a Phase 2 artifact

Phase 1: *"plus F7b, F10, F11, F12."* F11's fix column: *"`sys.stdin.reconfigure(...)`, guarded,
**in D2's `hooks_entry.py`**"* — a file Phase 2 creates. Either F11 slips to Phase 2, or Phase 1
patches `bin/sb-stop-hook:28` / `bin/sb-activity-hook:27` directly and Phase 2 re-does the work
when it folds them. Say which.

## 8. MEDIUM — the `windows-latest` leg has no owner and no green date

Phase 1's criterion is phrased "on `windows-latest`", so the leg lands at Phase 1. §4 lists what
will fail "in order" but no phase owns turning it green, and nothing says it should be
`continue-on-error` in the interim. As written it is red on every PR in the repo — including
unrelated ones — from Phase 1 through Phase 6. Decide: `continue-on-error` until Phase 7, or the
leg lands per-phase behind registered skips.

Related, smaller: §4 registers the `windows`/`posix` pytest markers *"in the new `pyproject.toml`"*
— a Phase 2 artifact — while Phase 1 is the phase that first needs Windows skips. Marker
registration has to move to Phase 1 or Phase 1 uses `skipif` and Phase 2 converts.

## 9. LOW-MEDIUM — Phase 3's herdr shell-family fact is an unresolved decision inside a phase

Phase 3: *"Needs a herdr-reported 'what shell does this pane run' fact — confirm herdr's API
exposes it."* That is a D-item, not a bullet. If herdr does not expose it, B5's whole design
changes, and §2's B5 row already spells out the blast radius: a dispatch that lands anywhere but
POSIX means `SbUnpinned` on **every macOS spawn**. Belongs in Phase 0 next to D5 — same kind of
thing, same "settle before touching the sites" logic.

(On D5 itself: the plan's Phase 0 handling is correct. D5 does gate B7, B7 is in Phase 1, so D5
before Phase 1 is right. No reordering needed there.)

## 10. LOW-MEDIUM — the shell-family builder test does not "cover B5"

§4: *"Command-string builders parameterized on shell family … Covers B5, F7, hooks."* It genuinely
covers the POSIX no-regression half (byte-identical string) and the dispatch default — both real,
both valuable. It does **not** cover the Windows half: "never emits a bare single-quoted path" is
a shape assertion, and whether the emitted cmd/pwsh string actually pins PATH and echoes something
`wait_output` matches cannot be pinned without a Windows shell. The part that decides `SbUnpinned`
is the branched **marker** at `broker.py:3348` matching what the pane really prints — un-pinnable
in CI. Honest to list the test; overstated to say it covers B5. §5's unproven list should name it.

## 11. LOW — Phase 1's `sb plugin list` is not launchable on Windows before Phase 2

There is no `switchboard/__main__.py` (checked), and `bin/sb` is unlaunchable on Windows (B6,
Phase 2). The criterion is satisfiable as `python bin/sb plugin list`, but as written it reads as
a forward dependency on Phase 2. Spell the invocation out.

## 12. LOW — D2's `.cmd` shim defeats the CI python-version axis (unverified)

`@py -3 "%~dp0sb"` resolves through the Windows launcher, not through the interpreter
`actions/setup-python` selected. Anything exercised *through* the shim on `windows-latest` is not
testing the matrix's 3.11/3.12 choice. Reasoned from the shim string in D2 — **I have no Windows
box and did not verify** the launcher's behaviour or its presence on the runner image.

## 13. LOW — F7 is split across phases without saying so

§2's F7 row covers `hooks.py:113/126/143` **and** `broker.py:3343`. Phase 2 claims "F7" but names
only `hooks.py`; Phase 3 names only B5/F8. B5's rewrite of `_ready_pane` almost certainly absorbs
`broker.py:3343`, but nothing in §3 says so, and F7 reads as done after Phase 2.

---

## What held under attack

- **The import-blocker set (B1–B4) is complete.** `grep -rn "^import |^from " switchboard/*.py
  defaults/plugins/*/__init__.py | grep -E "termios|tty|pty|pwd|grp|resource|curses|select|signal|fcntl|readline"`
  returns exactly: `fcntl` ×5, `board.py:55 termios`, `board.py:58 tty`, plus `select` and `signal`
  (both import fine on Windows). B3/B4 are correctly classified as runtime/attribute failures, not
  import blockers. Nothing else blocks import.
- **"Additive, no risk to existing legs" is true for the matrix change alone.** `tests.yml` has
  `fail-fast: false`, no caches, no `upload-artifact`, no matrix-wide steps — nothing for a new OS
  to collide with. The risk is the dep changes (finding 2), not the OS.
- **The code dependency graph is correct.** No phase's *code* requires a later phase's code. In
  particular Phase 3 (spawn) does not need Phase 4's procscan, and Phase 6 does not need anything
  Phase 1 only stubbed beyond the `rawinput.py` seam it explicitly defers. The ordering itself is
  fine; the criteria are what fail.
- **D5's placement is right.** It gates B7, B7 is Phase 1, Phase 0 settles it. No reorder.
