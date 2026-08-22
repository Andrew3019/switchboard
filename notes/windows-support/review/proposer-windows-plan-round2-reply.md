# Proposer reply — adversarial review round 2 (zero-regression / psutil blast radius)

All 8 findings **ACCEPTED**. I re-ran every measurable claim on this Mac rather than taking the
reviewer's numbers. Plan revised and committed: **d75be60**.

The reviewer's verdict is right and it is the most important thing they found: §5's blanket
sentence ("the POSIX side of every proposed change is a verbatim extraction of current code") was
**false for five of the proposed changes**, and two of them change macOS behaviour today.

## Per finding

| # | Verdict | What I re-verified myself | What changed |
|---|---|---|---|
| 1 `reconfigure` → `strict` + capture crash | ACCEPTED | reproduced **both** defects: `sys.stdout.errors` is `surrogateescape` under this repo's `LANG=C.UTF-8` and `strict` after; `StringIO` has no `reconfigure` → `AttributeError` | F10/F11 rewritten with explicit `errors=` + `getattr` guard; new hazard note; "no platform gate needed" and the inherited "zero-risk on POSIX" deleted |
| 2 CPU% semantics | ACCEPTED | `ps -o pcpu=` 50.5 vs `cpu_percent()` 0.0 then 80.8 on the same pid | **D1 cost 3** — definition change *and* the stateless-`procscan`-reads-0.0-forever constraint |
| 3 two-phase read | ACCEPTED | `broker.py:2437-2454`; the docstring calls the ordering deliberate | **D1 cost 4** + `procscan` rule 1 |
| 4 empty cwd | ACCEPTED | `is_under("", checkout)` → **True** against this very checkout | **D1 cost 5** + `procscan` rule 3 |
| 5 `Proc.command` drift | ACCEPTED | 17 of 277 differ on this machine | **D1 cost 7** (cosmetic, user-visible) |
| 6 F6 POSIX regression | ACCEPTED | all four sites are `X_OK ... else shutil.which` | F6 now `os.name`-gated, `os.access` kept verbatim on POSIX |
| 7 B5 dispatch default | ACCEPTED | plan text; Phase 3 concedes the herdr fact is unconfirmed | B5 defaults to POSIX when the fact is absent; §4 pins the dispatch, not just the string |
| 8 `panel.py:478` | ACCEPTED | grep gives 8 flock calls; the plan said "6" while listing 7 | B1 restated as 8 with the grep; note that one survivor keeps `import fcntl` alive |

Also folded in: **D1 cost 6** (ppid map from `ppid` alone — the reviewer's 213-of-536
`AccessDenied` measurement), which was inside finding 3 rather than a finding of its own.

## What I did *not* do

- Did not reopen D1–D4. Costs 3–7 are recorded as named costs of the settled psutil decision, not
  as arguments against it. Nothing here shows psutil is *unsafe* — every one has a stated fix.
- D5 is still the only open decision.

## Structural changes

- **§5's blanket sentence is gone**, replaced by a per-item regression table: what is verbatim,
  what is measured-no-op, and the five that regress macOS unless the stated fix is applied.
- **§4 gains six no-regression pins**, all runnable on macOS today — they are exactly the tests
  that would have caught these five.
- **`procscan`'s spec rewritten** from "one enumeration" (which was itself the bug) to four
  explicit rules.

## Credited as still-sound

`broker._parents` → psutil (536 procs, 0 ppid mismatches), the psutil cwd set (0 strings differ),
RSS (identical), `available` (0.9 MB apart = sampling skew), F9/F12 as true POSIX no-ops, F7/F3 as
clean forks, and the `lock(fd)` signature respecting `panel.acquire`'s "the fd IS the lock"
contract. All of that is now written into §5's table and the round-2 appendix entry.
