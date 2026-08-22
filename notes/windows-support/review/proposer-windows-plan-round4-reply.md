# Proposer reply — adversarial review round 4 (build model + seam coherence)

All 10 findings **ACCEPTED** — one with its prescription corrected. Committed **623f29c**.

**What held:** the phase graph, and two of the four new seams (`hooks_entry`, and `procscan` as a
*module* — its three callers genuinely don't conflict). `lockfile` and `rawinput` did not.

## The three you flagged

**(1) `procscan` AccessDenied — ACCEPTED, prescription corrected.** The gap is real and it is the
only rule whose absence fails toward *deletion*. But the reviewer's fix as written — "fail the
scan to `None` or count the pid as present" — **would have been a macOS regression**, and a bad
one. Measured here: **195 of 490** processes refuse `cwd()` on this Mac. Round 2 measured that
those refusals reproduce unprivileged lsof's own-user-only scope *exactly* (0 cwd strings differed,
0 pids psutil had that lsof did not). Applied unconditionally, either prescription makes `scan()`
return `None` or refuse on every call — `sb workspace close` permanently dead on macOS. So rule 5
is scoped:
- a refusal on a process the caller **does not own** is out of scope — today's behaviour, measured;
- a refusal on a process the caller **does** own, or whose ownership can't be read, **fails the
  whole scan to `None`** (the existing fail-safe channel). This is the Windows case that has no
  POSIX equivalent: a process you can't open may still be your own agent.

**(2) `lockfile` blocking mode — ACCEPTED, now D6, needs Andrew.** Six of eight sites are fine;
the two blocking ones (`plugins.py:687`, `plans:2869`) have no faithful Windows implementation.
The repo already has an opinion 200 lines away — `broker._fork_lock` polls `LOCK_NB` against a
named timeout, logs, and proceeds — but **the per-site expiry behaviour is the actual decision**:
"proceed anyway" is right for a fork lock and wrong for `_minting`, where proceeding means two
agents minting the same plan id. That is the part I will not pick.

**(3) Phase 1 ownership — ACCEPTED.** §3 now says: land `lockfile.py` and `rawinput.py` as one
prior commit with no sites converted, then **decompose by FILE, not fix-class**. The fix-class
split puts 3–4 concurrent writers in `board.py` and 2 each in six other core files, and nothing
forces it — the fixes are independent *within* a file.

## The other seven

- **B2 = Phase 6's structural half** — `import termios` can't leave `board.py` without all four
  call sites, all inside `main()`. And it is Phase 1's one untested edit: `tests/test_board.py`'s
  own comment at `:2470` says "Nothing tests `main()` itself". Now stated as the phase's real risk.
- **D4a (new, open, needs Andrew)** — the fallback must append to `linked` or `_exclude` never
  runs → git counts the copied `CLAUDE.md` as untracked → `_weigh` puts it in `dirty` →
  `broker.py:2381` **refuses the close outright**. Every Windows worktree uncloseable, and Phase
  5's criteria are green over it. Second half is a data-loss decision.
- **D5's cost corrected** — `sb doctor` does *not* police plugin imports (`cli.py:1428-1464`
  reports status/orphans/source/deprecations only). The contract is prose in one docstring, which
  was itself the plan's source and is wrong about doctor. Doesn't flip D5; the comparison was
  against a check that doesn't exist.
- **`rawinput` redrawn** — EOF, decode, and raw-mode save/restore all sit between the byte source
  and `parse_sgr`. API is `open_raw()` / `poll(timeout)` / explicit EOF, not "give me bytes".
- **F9/F12 enumerated** in a new appendix, by an **AST pass**. A grep is wrong in both directions:
  it misses bare `open(...)`, matches `os.open(...)` (an fd), and it reported `plans:3350` as a
  site when that call already passes `encoding=` on its continuation line. Both earlier drafts of
  this plan carried that error — which is the finding's own point about grep-defined scope.
- **`.lock` files are not 0-byte** — `panel.py:437-441` writes a pid under the lock. §5 gains
  `ftruncate`-under-lock and release-on-close/termination timing, which the single-collector
  election depends on.
- **Parallelism is within-phase only** — one line in §3 now says so, since `broker.py` is edited in
  five phases and `board.py` in five.

## FINAL consolidated list of what needs Andrew

Now a table at the top of §1. Five items, all Phase 0, none of them coding work:

| | question | gates |
|---|---|---|
| **H1** | Does herdr run natively on Windows and make a Windows pane? | Phases 3, 3b, 6, 7 |
| **H2** | Does herdr's API report a pane's shell family? | Phase 3 (B5) |
| **D5** | How does a plugin reach `lockfile` — re-export, or widen the contract? | B7, in Phase 1 |
| **D6** | What does `blocking=True` mean on Windows, and what expires per site? | `lockfile.py`, Phase 1 |
| **D4a** | Fallback: append to `linked`? and how is a copied `CLAUDE.md` classified? | Phase 5 |

H1 is the largest unproven claim in the document. D4a's second half and D6's per-site expiry are
the two that can lose data or corrupt state if guessed.

**D1–D4 are untouched, and no round found any of them unsafe.**
