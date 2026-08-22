# Adversarial review — port sequencing under switchboard's own multi-agent model + the four new seams

Reviewer: `reviewer-port-sequencing`. Artifact: `notes/windows-support/native-port-plan.md` @ `75e0a24`.
*(Path corrected 2026-08-22: this reviewed the **native-port** plan, which then lived at `notes/windows-support-plan.md` and is now `notes/windows-support/native-port-plan.md`. The file at `notes/windows-support-plan.md` today is the WSL2 plan, which this did NOT review.)*
Lens: (A) can this be BUILT by several agents in one shared worktree? (B) do the four new
shared seams hold together as designs?

**Verdict: needs changes before implementation starts.** Not a redesign — the phase graph and
three of the four seams survive. Two seams have real design holes (`lockfile` blocking mode,
`procscan`'s cwd AccessDenied rule), and Phase 1's work-breakdown is undefined in a way that
corrupts core files under the fan-out the plan's own presentation invites.

What I ran vs. what I read: every `file:line` below was opened in this checkout. Windows-runtime
claims (msvcrt semantics, psutil-on-Windows) are from documented CPython/psutil behaviour, **not
run** — no Windows box. Marked where it matters.

---

## 1. HIGH — `blocking=True` has no faithful Windows implementation

`lockfile.lock(fd, *, blocking)` is presented as "~40 lines", POSIX extracted verbatim. The eight
sites are not uniform, and the split matters:

| site | mode | released by |
|---|---|---|
| `plugins.py:687` | `LOCK_EX` **blocking**, held for a whole handler call | `os.close(fd)` (`:689`) |
| `defaults/plugins/plans/__init__.py:2869` | `LOCK_EX` **blocking**, held across a `yield` | `os.close(fd)` (`:2872`) |
| `sweep.py:308` | `LOCK_EX\|LOCK_NB` | `os.close(fd)` (`:323`) |
| `panel.py:435` (`acquire`) | `LOCK_EX\|LOCK_NB`, held for the collector's life | `LOCK_UN` `:453` / exit |
| `panel.py:453` (`release`) | `LOCK_UN` | — |
| `panel.py:474`/`:478` (`collector_running`) | `LOCK_EX\|LOCK_NB` then `LOCK_UN` | — |
| `broker.py:2863` | `LOCK_EX\|LOCK_NB` in a poll loop w/ deadline | `os.close(fd)` (`:2880`) |

The two blocking sites are the problem. `msvcrt.locking(fd, LK_LOCK, n)` does **not** block
indefinitely: it retries once a second, ten times, then raises `OSError`. There is no unbounded
wait in `msvcrt`. So on Windows:

- `plugins.locked` (`plugins.py:669-690`) is documented as holding the lock "for the length of a
  handler call" — arbitrary duration. A second agent contending for >10s gets an exception where
  POSIX waits. `plugins.locked` is the mechanism the docstring at `:672-676` advertises as the
  answer to "what happens when two agents write at once".
- `plans._minting` (`:2869`) same shape.

The retry/deadline policy is a **design decision, not an implementation detail** — and the repo
already has an opinion about it two hundred lines away: `broker.py:2856-2876` polls `LOCK_NB` with
`FORK_LOCK_WAIT`, logs `fork_lock_timeout`, and proceeds anyway, with a docstring
(`broker.py:2843-2847`) arguing that an unbounded wait is the worse failure. The plan should either
adopt that shape for the Windows `blocking=True` branch with a named timeout and a stated
expiry behaviour per site, or say why `plugins.locked` may raise on Windows and POSIX not.

*Evidence:* CPython `msvcrt.locking` documented behaviour (read, not run). Call-site modes: grep
`flock` over `switchboard/*.py defaults/plugins/plans/__init__.py`, all eight opened.

## 2. HIGH — `procscan` has no AccessDenied rule for the cwd scan, and that gap fails UNSAFE

The four rules in §2 cover the ppid read (rule 2: never combine the fetch, never drop an
`AccessDenied` process, or `_ancestry` truncates) and cover empty cwd (rule 3). Nothing covers
**a cwd psutil refuses to read**. On Windows `Process.cwd()` raises `AccessDenied` for processes
the caller cannot open; on macOS today it raises for foreign processes too.

The obvious implementation — skip the pid — makes `live.processes_in` under-report. That feeds
`broker._live_under` (`broker.py:2443`), which feeds the close gate. Under-reporting there means
`sb workspace close` **destroys a checkout somebody is standing in**.

Every other rule in D1 pushes toward refusal, which is the fail-safe (`broker.py:2305`, and rule 3
is explicitly about "refuses forever" being the safe direction). This is the one that pushes
toward deletion, and it is the one the plan does not name. Today's lsof path cannot have it:
`live._parse` gets a name or the process is simply absent from lsof's output for a reason lsof
already decided.

Needs a fifth rule: a cwd the scan cannot read is **not** "not in the directory" — either fail the
whole scan to `None` (the existing `scan() -> None` fail-safe channel) or count the pid as present.

## 3. HIGH — Phase 1 has no ownership axis; its natural fan-out collides on six core files

Phase 1 bundles five independent fix-classes. Decompose by fix-class — which is how the plan
presents them, and how a lead reading §3 would spawn — and the writers overlap:

- `broker.py` — lockfile (`:33`, `:2863`) **+** encoding (`:1134`, `:4090`)
- `panel.py` — lockfile (`:69`, `:435/453/474/478`) **+** encoding (`:136`, `:145`)
- `plugins.py` — lockfile (`:62`, `:687`) **+** encoding (`:336`)
- `sweep.py` — lockfile (`:44`, `:308`) **+** encoding (`:313`, `:319`)
- `collector.py` — SIGHUP (`:768`) **+** encoding (`:568`)
- `board.py` — rawinput (`:55`, `:58`) **+** signals (`:2414`, `:2422`) **+** encoding (`:2179`)
  **+** stdio/F10 (`:2333`) — **three or four** concurrent writers
- `defaults/plugins/plans/__init__.py` — B7 lockfile (`:379`, `:2869`) **+** encoding (`:3350`,
  `:3848`) **+** F12

The plan never says who owns what. Nothing in Phase 1 forces this: the fixes are independent
*within* a file. The fix is one sentence in §3 — **decompose Phase 1 by FILE, not by fix-class**
(one worker owns a file set and applies every Phase-1 fix in it), after `lockfile.py` and
`rawinput.py` land as one prior commit that everything else edits against.

## 4. HIGH — F9 and F12 are grep-defined, not enumerated, so they cannot be split at all

§2's F9 says "the grep is `grep -rn -e 'read_text(' -e '.open(' -e 'write_text(' switchboard/
defaults/`, minus the lines that already pass `encoding=`" and F12 says "26 sites … e.g." — three
examples. Two workers running that grep at different points in the phase get different, overlapping
sets, and neither can tell whose line is whose. A work item whose scope is a grep has no boundary,
and Phase 1's exit criterion (2) is itself a grep, so a partial pass reads green.

Needs a committed, enumerated site list (file:line, both trees) before Phase 1 fans out. §2's F9
row already half-does this for `switchboard/`; `defaults/` and all of F12 are still a grep.

## 5. MEDIUM-HIGH — Phase 1's B2 *is* Phase 6's F3/F4, and it is the plan's one untested edit

`import termios` cannot leave `board.py` without every call site leaving with it. There are exactly
four, all inside `board.main()`:

- `board.py:2395` `termios.tcgetattr(fd)`
- `board.py:2406` `termios.tcsetattr(...)` — inside `restore()`, which is also the SIGINT/SIGTERM
  /SIGHUP handler's teardown (`:2410-2414`)
- `board.py:2452` `tty.setraw(fd)`
- `board.py:2473` `select.select([fd], [], [], 0.25)`

So Phase 1 necessarily performs Phase 6's structural half. That is fine if said; the plan reads as
if Phase 1 only moves imports and Phase 6 moves the loop.

What is not fine: `tests/test_board.py` is 2537 lines and **never calls `board.main()`** — it
covers `parse_sgr`, `glyph`, `draw`, layout, click resolution. Phase 1's three exit criteria
(imports succeed / grep is clean / `plugin list` reports nothing broken) are all green over a
board whose raw-mode setup or signal-path restore was broken during the extraction. §3 calls
Phase 1 "pure extraction on POSIX"; for the lockfile sites it is, for this one it is not.

*Fix direction:* either a POSIX-runnable test that drives `main()` through a pty for one frame
before Phase 1 touches it, or state in §3 that this edit is hands-on-verified only and is the
phase's real risk.

## 6. MEDIUM — the `rawinput` seam is cut in the wrong place

"Keep `parse_sgr` shared, fork only the byte source" is right about `parse_sgr` and wrong about
where the fork ends. Three things sit *between* the byte source and `parse_sgr`, all POSIX-shaped:

1. **EOF.** `board.py:2474` `if not data: break` is the loop's only exit on closed stdin.
   `msvcrt.kbhit()` has no EOF to report — the Windows source cannot express it, so the seam needs
   an explicit "source exhausted" signal or the board never exits that way on Windows.
2. **Decode.** `board.py:2477` `data.decode("utf-8", "replace")`. `msvcrt.getch()` returns bytes in
   the *console input codepage*, `getwch()` returns `str`. Neither is UTF-8 bytes, so the decode
   forks too and cannot stay on the board side of the seam.
3. **Which handle.** `board.py:2394` `fd = sys.stdin.fileno()` is used for `tcgetattr`, `setraw`
   and `select`. Windows console mode is set on `GetStdHandle(STD_INPUT_HANDLE)`, which is not that
   fd under redirection — and `restore()` (`:2398-2406`) runs from a signal handler, so the
   save/restore pair has to live inside `rawinput` too, not just the read.

Whether `ENABLE_VIRTUAL_TERMINAL_INPUT` delivers SGR mouse bytes at all is V5 and already flagged
unproven. These three are structural and readable from the source today. The seam's API needs to be
`open_raw() -> ctx` / `poll(timeout) -> Optional[str]` / EOF, not "give me bytes".

## 7. MEDIUM — D4's fallback: the plan gates on `is_symlink`, and the real break is `_exclude`

`link_config` (`broker.py:1108-1121`) calls `self._exclude(main, LINKED_CONFIG)` **only when
`linked` is non-empty** (`:1119`). The plan does not say whether the junction/copy fallback appends
to `linked` or, like today's failure path (`:1119-1120`), just logs `link_failed`. If it does not
append:

1. `.git/info/exclude` never gets the names.
2. git reports the copied `CLAUDE.md` as untracked, so `_weigh` counts it in `dirty`
   (`broker.py:1851-1855`, the `code != "!!"` branch).
3. `broker.py:2381-2383` — `if weight["dirty"]:` — **refuses the close outright**. Not a prompt.
   Every Windows worktree in the fallback branch becomes uncloseable.

Phase 5's two exit criteria are both about the two `is_symlink()` sites classifying the link as
ours. Both are green over this.

Second, and worse in kind, at `broker.py:1856`: a **copy** of `CLAUDE.md` is byte-indistinguishable
from one the user wrote. Classifying it `mine` means a genuine file is deleted without ever
appearing in the "what you're about to lose" inventory that `_weigh`'s docstring
(`broker.py:1834-1838`) says the whole thing exists for. Classifying it `unknown` means every
Windows close prompts. The plan's "so a junction/copy isn't misread as 'not ours'" picks the first
without naming it as a data-loss decision. It is one, and it is D4's, not an implementer's.

## 8. MEDIUM — D5's cost comparison rests on a check that does not exist

D5 presents option 2 (widen the contract to allow `switchboard.lockfile`) as costing a change to
`sb doctor` as well as the prose. `_doctor_plugins` (`cli.py:1428-1464`) reports
`status in ("broken", "incompatible")`, orphaned state dirs, repo-sourced plugins and deprecations.
It **does not inspect what a plugin imports**. The only statement of the one-module contract
anywhere is prose in one plugin's docstring, `defaults/plugins/report-bug/__init__.py:286-288`
("the one switchboard module a plugin is allowed to import … the contract `sb doctor` polices") —
which is the plan's own source for the claim, and it is wrong about doctor.

This does not obviously flip D5 (option 1's re-export is still the smaller change), but the
decision is being made on a cost that is a docstring edit.

**On my lens's own question:** D5 is *not* a cross-worker coordination problem either way. Option 1
touches `switchboard/plugins.py` + `defaults/plugins/plans/__init__.py`; per finding 3 those should
be one worker's files in Phase 1 anyway.

## 9. LOW-MEDIUM — `.lock` files are not 0-byte, and half the sites have no explicit unlock

§2 states "All 8 lock calls are whole-file, advisory, exclusive, cross-process, on a *separate*
0-byte `.lock` file". `panel.acquire` (`panel.py:437-441`) `ftruncate`s the lock file and writes
its own pid into it **while holding the lock**. So `collector.lock` is not 0-byte, and the Windows
branch has an unproven interaction (`ftruncate` under a byte-range lock at offset 0) that §5 does
not list — §5 lists only "msvcrt byte-range lock on an empty file". The plan's
`os.lseek(0)`-before-lock rule does already handle the file-pointer drift this write causes, so
this is a wrong statement plus one missing V-item, not a break.

Separately, four sites release by closing the fd with a comment saying so — `plugins.py:689`,
`sweep.py:323`, `broker.py:2880`, `plans:2872` — and `panel.py:426-430` rests the entire collector
election on the kernel dropping the lock at process exit, "`kill -9` and a herdr restart included".
Windows does release byte-range locks on handle close and on termination, but MSDN documents that
timing as resource-dependent and recommends explicit unlock. That belongs in §5's unproven list;
the election is the fleet's single-collector invariant.

**Checked and held:** no call site reads a `.lock` file's body. `sweep.claim` reads `slot`
(`sweep.py:312`), a *different* file, while holding `slot.lock`; nothing reads `collector.lock`'s
pid back. The plan's "never read a `.lock` file's contents without holding the lock" rule is
satisfied by all eight sites as they stand.

## 10. LOW — the phase graph is near-serial through `broker.py`/`board.py`, and §3 doesn't say so

`broker.py` is edited in Phases 1, 2, 3, 4 and 5. `board.py` in 1, 2, 3, 6 and 7. `panel.py` in 1
and 3b. That is not a defect — phases are sequential by dependency and round 3 confirmed the code
graph holds — but it means **all** of this port's parallelism has to come from within a phase,
which is exactly what finding 3 says is undefined. One line in §3 stating it would stop a lead
from expecting cross-phase overlap that isn't there.

---

## Held under attack (checked, no finding)

- **`procscan`'s three callers do not conflict.** `live.scan` (cwd, point-in-time) and
  `broker._parents` (ppid) are both one-shot reads in the same short-lived `sb` process, in that
  order (`broker.py:2443-2454`). The retained-`Process` state that rule 4 needs for CPU% lives only
  in the long-lived collector (`stats.py:166`, behind `_PROC`), a different process that calls
  neither of the other two. A module of stateless functions plus one stateful sampler class is
  coherent. Round 2's "not one enumeration" correction already removed the contradiction; the brief's
  suspicion that cpu%-over-time and point-in-time cwd/ppid cannot share one abstraction does not land.
- **`parse_sgr` really is platform-neutral.** `board.py:139-167` is pure string work over a regex,
  with the split-sequence carry in `leftover`. Keeping it shared is right; the seam problem is
  everything *upstream* of it (finding 6).
- **The `lock(fd)` / `unlock(fd)` signature is right.** `panel.acquire` returns the fd as the lock
  (`panel.py:426-430`, `:436`), `panel.release` takes it back (`:448-455`), and `collector_running`
  needs lock-then-unlock on an fd it opened itself (`:470-480`). A path-taking API would break all
  three. Round 2 got this one right.
- **`broker`'s fork lock is already a poll loop**, not a blocking flock (`broker.py:2856-2876`), so
  it converts to `blocking=False` cleanly and is untouched by finding 1.
- **No lock is held across a spawn in a way that matters.** `broker._fork_lock` yields while `git
  worktree add` runs, but CPython fds are non-inheritable by default, and `plugins.locked`'s
  docstring (`:679-680`) states it is "never held over the spawn path".

---

## Answer to the brief's closing question

**Can this plan be executed by switchboard's own multi-agent model?** Yes, but not as written —
Phase 1 needs an explicit by-file ownership split and an enumerated F9/F12 site list first
(findings 3, 4). Phases 2-7 are small enough that one or two agents each is the natural shape, and
the near-serial `broker.py` traffic (finding 10) is a consequence of the dependency graph, not a
defect in it.

**Do the four new seams' designs hold together?** `hooks_entry` yes. `procscan` yes as a *module*,
with one missing rule that fails in the unsafe direction (finding 2). `lockfile` no — its blocking
mode has no Windows implementation and needs a policy decision (finding 1). `rawinput` no — the
seam boundary is drawn one layer too low and has to own decode, raw-mode save/restore, and EOF
(finding 6).
