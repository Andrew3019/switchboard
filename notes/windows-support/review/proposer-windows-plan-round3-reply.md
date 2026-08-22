# Proposer reply — adversarial review round 3 (phase ordering / testability)

All 13 findings **ACCEPTED**. Each re-verified against the real files in this worktree.
Committed **75e0a24**. §3 was rewritten rather than patched — nearly every phase's exit criteria
was affected.

**What held:** the ordering itself. The 0→1→2→3→3b→4→5→6→7 code-dependency graph, D5's placement,
and the completeness of the B1–B4 import-blocker set all survived. Every defect was in what the
gates *check*, plus one environment dependency the plan never named.

## The three you flagged

| | Verdict | What I found |
|---|---|---|
| **(1) herdr-on-Windows** | ACCEPTED — **and it needs Andrew** | I could **not** establish that herdr has a Windows build. `herdr.py:1-11`: external binary, pinned 0.8.0 / protocol 19, the only thing that makes a pane. The only claim anywhere is an unevidenced parenthesis in the herdr-integration audit (line 6, "already Windows-native") — and that same audit says at line 108 it does not know where a Windows herdr installs, which is not what a verified claim looks like. Now **H1**, a Phase 0 question, and §5's largest unproven item. |
| **(2) psutil turns existing legs red** | ACCEPTED | Read `tests.yml` in full: install step is `pip install --upgrade pip pytest`, run step is `python -m pytest tests`, **no `pip install -e .`**, and the header comment states the no-deps premise outright. Phase 4 now owns that edit, and the header has to be rewritten with it. Also folded in the off-CI half: `panel.py:578-587` spawns the collector with `stderr=DEVNULL`, so a missing psutil is B7's exact shape on macOS — `procscan` must fail loudly. |
| **(3) Phase 1 criterion + stale counts** | ACCEPTED | Ran `./bin/sb plugin list`: `todo` reads `not enabled` (`defaults/plugins.toml:61` ships it off; `plugins.py:425-426`). The old criterion was unsatisfiable on a healthy Mac today. Now "**no shipped plugin reports `broken`**", invoked as `python bin/sb` (no `__main__.py`, confirmed), and **grepped** — `cli.py:1411` returns `0` unconditionally. Verified it still catches B7: `plugins.py:429` overwrites `not enabled`, and `load_all` imports regardless of enablement. Counts measured: `switchboard/` has **4** imports and **7** flock calls, `defaults/` adds 1 and 1 — neither is 5 and nothing is 6. |

## The other ten

- **4** Phase 2's gate split: the `.cmd`-shim half is provable this phase; the Stop-hook half is
  deferred to Phase 7 and says so (it was already on §4's cannot-be-CI'd list).
- **5** Phase 5 split into two criteria, one per D4 branch — the old one tested only the fallback,
  i.e. the path Andrew will not use, and `windows-latest` runners are elevated so CI cannot reach
  it anyway. Both criteria now also assert M5's two detection sites.
- **6** Phase 4's criteria reworded to fail on D1 costs 3 and 5 — `0.0` is a "populated" number,
  and refusal is the fail-safe, so both old criteria were green over the predicted failure.
- **7** F11 scheduled explicitly: Phase 1 patches the two `bin/` scripts directly; Phase 2 carries
  the fix into `hooks_entry.py`. §2's F11 row says so too.
- **8** `windows-latest` lands at Phase 1 with **`continue-on-error: true`**, dropped at Phase 7;
  markers register in Phase 1 (`pytest.ini`) and move to `pyproject.toml` at Phase 2.
- **9** H2 (does herdr report a pane's shell family?) promoted from a Phase 3 bullet to a Phase 0
  question, next to D5 and H1.
- **10** §4 no longer claims the builder test "covers B5" — it covers the POSIX half and the
  dispatch default; the Windows marker match is in §5 as unproven.
- **11** invocation spelled out as `python bin/sb plugin list`.
- **12** recorded in §5 as an unverified caveat (the reviewer had no Windows box), with the
  mitigation named — a shim spelled `python "%~dp0sb"` rather than `py -3` sidesteps it without
  reopening D2.
- **13** F7's `broker.py:3343` half stated as Phase 3 work, absorbed by B5's rewrite. F7 is not
  done at the end of Phase 2.

Also dropped: "Phases 1–5 are largely CI-verifiable", replaced by a per-phase statement.

## Needs Andrew

Three open items, all Phase 0, none of them coding work:

1. **H1 — does herdr run natively on Windows and make a Windows pane?** The largest unproven claim
   in the document. If no, Phases 1/2/4/5 all land and pass their gates and switchboard still
   spawns nothing — this plan's signature failure mode at plan scale.
2. **H2 — does herdr's API report a pane's shell family?** Decides B5's design; same conversation.
3. **D5** — how a plugin reaches `lockfile` (from round 1, still open).

D1–D4 untouched.
