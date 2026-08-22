# Adversarial review of the WSL2-first plan — synthesis

2026-08-22. Review of `notes/windows-support-plan.md`. Four rounds run (hit the 4-round cap, but
substantively converged — see below). One standing proposer, one fresh single-lens reviewer per
round, never a reused lens. Investigation/review only; no production code changed.

## Bottom line
The **WSL2-first recommendation is sound** and is now well-supported. It was **never attacked in
any round** — every round instead removed a comfort the plan had asserted but not earned, and the
proposer **revised on all points across all four rounds, rebutting nothing**. Plan status line now
reads "ready for PR #171 to be updated". Tree clean.

Commits on `lead-windows-support-plan`: `6b2a69a` (R1), `6f17add` (R2), `c1a732e` (R3),
`50668d8` (R4), plus `e5e77ad` (R1 response record).

## What the plan is now
- Still recommends running switchboard inside WSL2 — but honest about **three real costs, not
  zero**: (1) one required code fix, (2) one required herdr config step, (3) the `/mnt/c`
  placement rule.
- §3 is now an actual **17-step setup guide** (was an outline) with `[W]`/`[L]` markers separating
  unvalidated Windows-side steps from source-verified Linux-side ones, a support-matrix, a
  verification step, and a day-2 section.
- The three cited evidence docs now carry **dated correction banners**, so following the plan's own
  pointers no longer hands the reader a retracted claim.

## Which objections changed it (one lens per round, each new)
**R1 — "does every native blocker dissolve?"** Killed the **"zero code changes"** claim.
- The lsof liveness path (native blocker F1) is **measured broken** on Ubuntu 24.04 (the
  `wsl --install` default): its lsof emits 3-line `-F pcn` groups that switchboard's parser
  rejects, and `broker.py:2299-2311` turns the resulting `None` into a **permanent "cannot close"
  refusal** — so `sb cleanup` / `sb workspace close` would be dead under WSL2. One-character fix
  (`-F pcnf`) verified across five images incl. macOS.
- Also dropped the **"CI-tested on Linux"** overclaim: CI runs no herdr, no tmux, no real
  pane/agent/fleet (`.github/workflows/tests.yml:17-21`) — i.e. not the surface Windows support is
  about. And "every blocker is Windows-gated" was literally false for the ~52 locale-gated encoding
  sites.

**R2 — "is herdr under WSL2 clean?"** Killed **"setup is just installs"**.
- herdr **does** runtime-detect WSL and diverge (draws its own cursor → CJK IME anchor cost;
  forces clipboard writes to OSC 52) — all client-side rendering, so switchboard doesn't depend on
  it, but the "herdr treats WSL as plain Linux" wording was wrong.
- The one finding that touches switchboard: **`sb block`'s doorbell can silently fail** on a stock
  WSL2 distro (herdr's notification backend list excludes Windows Terminal; the system route needs
  `notify-send`, not installed). herdr returns `shown:false` as a **success** response and broker
  only logs on HerdrError, so **switchboard cannot detect it**. Now a required config step (§2.3,
  §3).

**R3 — "does §3 serve a non-technical user?"** Killed **"the deliverable is mostly a setup guide"**.
- §3 was an outline, not a guide. Step 7 even **reintroduced the exact silent-config failure §2.3
  exists to prevent** (wrong TOML table `[toast]` vs herdr's real `[ui.toast]`, silently ignored).
- "install switchboard exactly as on macOS/Linux" pointed at a procedure that doesn't exist (README
  says nothing to install; `sb` reaches PATH via one hand-made symlink documented only in a
  broker.py comment). Python 3.11 hard floor (tomllib) and the Ubuntu 22.04-vs-24.04 collision
  surfaced; §3 rewritten into a real guide.

**R4 — "internal coherence after heavy revision?"** No new risk; seam/consistency cleanup.
- Worst: the **cited research docs still asserted the retracted claims** (F1 "Dissolves";
  "zero Windows-specific code"), so the plan's own pointers gave the withdrawn story. Fixed with
  dated banners. The native-port **fallback** doc's §0 still prescribed removing the
  `tests/test_live.py:70` skip (would turn a documented gap into a red build) — struck through.
- TL;DR/§4/§6 seams, dead cross-refs, and marker gaps all fixed. §6 confirmed **honest and not
  over-hedging**; three inferred-but-load-bearing assumptions added to it (that `wsl --install`
  gives 24.04; the distro Python versions; that a fresh herdr install has no claude integration).

## Raised and rejected
- Nothing was rebutted by the proposer.
- "`sb init` is a missing setup step" was checked and is **not** a defect: `store.main_checkout()`
  infers the checkout (`store.py:122-132`) and `_refuse_outside_main_checkout` skips rather than
  guesses, so `sb start` works on an ordinary clone.

## Convergence note
We hit the **4-round cap**; round 4 still changed the artifact (coherence fixes), so this is the
cap rather than a clean no-change round. But the review **substantively converged**: the
recommendation survived every lens untouched, and the class of defect shrank each round —
technical blocker (R1) → feature degradation (R2) → guide usability (R3) → bookkeeping (R4). No
reviewer found a new showstopper after R1's lsof.

## Still open — for the parent to route (not review findings; review was investigation-only)
1. **The §2.1 lsof fix (`-F pcnf` in `switchboard/live.py`) must actually land in code** before
   anyone is handed §3 — the plan now depends on it shipping. Currently unmade.
2. **`scripts/00-preflight.sh:26`** tells readers to run `herdr integration install claude`, which
   `herdr.py:320-335` refuses to start with — stale, install-breaking, unrelated to Windows. Needs
   its own fix.

Per-round proposer dispositions: `notes/windows-support/review/proposer-response-round{1,2,3,4}.md`.
Per-round reviewer detail: `.switchboard/notes/reviewer-*.md` (session-local).
