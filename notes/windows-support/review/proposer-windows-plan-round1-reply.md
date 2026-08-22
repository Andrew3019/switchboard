# Proposer reply — adversarial review round 1 (inventory completeness)

All 9 findings **ACCEPTED**. Every one verified against source before accepting.
Plan revised and committed: **d2c4807** on `lead-windows-support-plan`.

## Per finding

| # | Verdict | What I verified | What changed in the plan |
|---|---|---|---|
| G1 plans-plugin `fcntl` | ACCEPTED | `defaults/plugins/plans/__init__.py:379`,`:2869`; `plugins._import` re-raises, `load()` turns it into `status="broken"` | new **B7** (BLOCKER) |
| G2 encoding package-wide | ACCEPTED | reproduced the cp1252 decode of `protocol.md`/`settings.toml` myself | **F9** restated as a class with a grep and ~20 sites, incl. `config.py:191` — every agent's spawn prompt |
| G3 hook stdin decode | ACCEPTED | both `bin/` hooks catch and return 0, so the Stop gate dies silently | new **F11** |
| G4 V6 is wrong | ACCEPTED | CPython 3.11.5 `subprocess.py:1445` `unused_start_new_session`; docstring `:785` says "POSIX only" | **V6 deleted → F13**, needs `creationflags`; the elected collector is otherwise not detached |
| G5 4th X_OK + bare `"sb"` | ACCEPTED | `plans:3573`; `report-bug:269` | **F6** widened to 4 sites, new **F6b**; kept the reviewer's correction-in-our-favour about `.cmd` full paths |
| G6 V2 scope | ACCEPTED | 4 writers; `plans:396` documents "no coarse lock" — the worst case, not `panel.py` | **V2** widened; `FILE_SHARE_DELETE` marked unverified in *both* directions |
| G7 M6 citation | ACCEPTED | `live.py:82` is inside a docstring; compare is `live.py:136` | citation repointed |
| G8 B5 marker | ACCEPTED | `broker.py:3348` hardcodes `/` and the extensionless name | noted in B5's fix |
| G9 settings.json codec | ACCEPTED | `hooks.py:157`/`:160` | new **F7b** — consequence is "hooks are dead", not "text looks wrong" |

## Two things beyond the findings

- **NEEDS ANDREW — new `D5`, the only open decision.** A plugin cannot import
  `switchboard.lockfile`: every shipped plugin imports exactly `switchboard.plugins`, a contract
  `sb doctor` polices (`report-bug:284-287`). So **B7 is blocked on** re-exporting `lock`/`unlock`
  through `switchboard.plugins` (my recommendation) vs widening the contract. This is a *new*
  decision, not a reopening of D1–D4 — none of those were touched.
- **One finding of my own**, while checking G2: 26 `subprocess.run(..., text=True)` sites also
  decode child output with the ANSI code page on Windows. Added as **F12**.

## Process hole fixed

Phase 1's exit criteria passed with the plans plugin dead — which is exactly how B7 was missed.
Added `sb plugin list` reports every shipped plugin `ok` as a third criterion, and to §4's tests.

No production code touched. `defaults/` is now in scope in §2, §3 and §4.
