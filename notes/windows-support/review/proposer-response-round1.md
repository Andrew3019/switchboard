# Proposer response — adversarial review round 1 (blocker dissolution under WSL2)

Reviewer: `reviewer-blocker-dissolution`. Proposer: `proposer-wsl2-plan`. 2026-08-22.
Outcome: **REVISED on all five points — nothing rebutted.** Commit `6b2a69a` on
`lead-windows-support-plan`. Only `notes/windows-support-plan.md` and this directory's notes
were touched; no production code.

## The headline: I measured the one open question, and F1 is worse than the review said

The review asked for F1 to be *demoted to Medium* and for an unprivileged-Linux lsof check to be
added to §6 as future work. I ran the check instead. Full detail and the table in
`../lsof-linux-measurement.md`; the result:

- lsof **4.95.0** — shipped by **Ubuntu 24.04, the distro `wsl --install` installs by default** —
  emits **3-line** `-F pcn` groups, with no `fcwd` line.
- `live._parse` (`live.py:100-113`) rejects the entire scan, `scan()` returns `None`, and
  `broker.py:2299-2311` refuses `sb cleanup` / `sb workspace close` **permanently**.
- So F1 is not "Medium confidence, unproven" — it is **measured broken** on the exact target.
- Exit code was **0** in every case, privileged and not. The exit-code branch (`live.py:94`) that
  the review flagged as a co-hazard is not the hazard; the shape check alone is.
- **The fix is one character:** `-F pcnf`. Verified to produce the expected 4-line group on all
  five images tested, macOS lsof 4.91 included — so it is not a Linux special-case.

Corollary the plan now records: `tests/test_live.py:70`'s darwin-only skip and the CI comment at
`tests.yml:17-21` are **correct**, and `audits/researcher-process-liveness-findings.md`'s headline
("the Linux lsof parse bug does not reproduce") is **wrong** — it tested lsof 4.93.2 only
(Ubuntu 22.04 / Debian 11, both superseded). Acting on its "un-skip that test on Linux"
recommendation would have turned a documented gap into a red build.

## Point by point

| # | Review's point | Disposition | What changed |
|---|---|---|---|
| 1 | "CI-tested on Linux" is an overclaim | **REVISED** | Phrase removed from the TL;DR and from §4's WSL2 row. §1 now carries the `tests.yml:17-21` caveat under the table, and §6 names the unexercised pane/agent/fleet surface on Linux as the largest remaining unknown — and as a *Linux* question, not a Windows one. §3 step 7 warns the WSL2 user is the first to exercise it. |
| 2 | F1 may not dissolve | **REVISED** (and escalated) | See above. §1's row reads **"Does NOT dissolve … Measured broken"**; new **§2.1** carries the mechanism, the measurement and the fix; TL;DR changed from *"essentially zero switchboard code changes"* to *"one required fix, not zero"*; §3 gains it as a step; §4's WSL2 row and §5 updated to match. |
| 3 | §1's "every blocker is Windows-gated" is literally false | **REVISED** | §1 retitled *"every **Windows-gated** blocker dissolves"*. The ~52-site encoding class is now its **own table row**, marked locale-gated rather than Windows-gated, with the weaker argument stated honestly ("the locale happens to be UTF-8", confidence Medium) instead of the stronger one §1 makes for real Windows branches. The §1/§2 contradiction is gone. |
| 4 | §2.3's "zero-risk" is measured false; counts wrong | **REVISED** | "zero-risk" retracted. §2.4 now shows the measurement (`surrogateescape → strict`; `hasattr(io.StringIO(), 'reconfigure') → False`), separates F9/F12/F7b (true POSIX no-ops) from **F10/F11** (require `errors=sys.std*.errors` **and** a `getattr` guard), and corrects *"~a dozen"* to **26 (F9) + 26 (F12) + F7b + F10/F11**. |
| 5 | §2.1's "/mnt/c is slow, not broken" is false | **REVISED** | §2.2 rewritten as a **correctness** rule. Leads with the silently-swallowed DrvFs symlink failure (`broker.py:1116` `symlink_to`, `1117-1118` catches `OSError` into a `link_failed` event and continues), then M6 case-folding at `live.py:136`, then `flock` over DrvFs as unverified; the 10–100× slowdown is demoted to a fourth reason. Hedged as documented WSL behaviour, not run — and added to §6. |
| minor | `bubblewrap` missing from §3 | **REVISED** | Added to step 4 with the citation to `researcher-wsl2-viability-findings.md` §2. |
| minor | herdr runtime-detects WSL (`linux.rs:38-49`) | **Noted, not folded in** | Accepted as accurate and as good evidence herdr's authors exercise WSL. Left out of the plan deliberately: it is a cosmetic cursor default on an identical Linux target triple, and §1's framing ("the Windows branches do not execute") survives it intact. Recorded here so the decision is visible rather than an omission. |

## Nothing rebutted

Every objection held on inspection. The two the review sourced from the repo's own committed test
and CI comment (points 1 and 2) were the load-bearing ones, and the tracked code was right where
the plan's supporting audit was wrong — which is the failure mode worth naming: the plan inherited
a confident audit headline without noticing it contradicted a tracked test, and no one had re-run
the audit's command on a current distro.
