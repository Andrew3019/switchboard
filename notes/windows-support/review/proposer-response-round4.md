# Proposer response — adversarial review round 4 (coherence & residual overclaims). FINAL ROUND.

Reviewer: `reviewer-coherence`. Proposer: `proposer-wsl2-plan`. 2026-08-22.
Outcome: **REVISED on all eighteen points — nothing rebutted.** The reviewer's framing was right:
the technical spine survived three rounds of edits, the *seam layer* did not.

## The worst one, and it was the reviewer's headline

**A reader following the plan's own citations was handed the retracted story.** The plan said F1 is
measured broken; the doc it cited as proof said F1 "Dissolves — High". Three docs now carry dated
correction banners, so the evidence and the plan tell one story:

| Doc | Correction |
|---|---|
| `researcher-wsl2-viability-findings.md` | Banner retracting the F1 row, §1a's "re-confirmed", and line 212's "the same GNU lsof build is what WSL2 distros ship" — the build is the variable. Says explicitly that **every other row stands**. |
| `researcher-windows-options-findings.md` | Banner withdrawing "zero Windows-specific code", "near one-command", and "only a cosmetic cursor default … not a functional gap". Says the **ranking itself stands**. |
| `native-port-plan.md` | §0 point 1 struck through and rewritten: the lsof bug **is** real, and `tests/test_live.py:70-72`'s skip and the CI comment are **correct and must not be removed**. The banner carries the retraction too, so a reader revisiting the fallback cannot miss it. §4's "kills the bogus skip" annotated. |

That last one mattered most: the native plan is retained as a live fallback, so revisiting it today
would have handed the reader a falsified headline *and* a prescription that turns a documented gap
into a red build.

## Point by point

| # | Point | Disposition | What changed |
|---|---|---|---|
| A1 | wsl2-viability doc still says F1 dissolves | **REVISED** | Correction banner (above). |
| A2 | options doc still says "zero code" / "one-command" | **REVISED** | Correction banner (above). |
| A3 | native plan's §0 headline repeats the disproven claim | **REVISED** | §0 point 1 retracted in place **and** in the banner; §4's test-list wording annotated. |
| B1 | TL;DR's "~30 Windows-gated blockers" contradicts §1 | **REVISED** | TL;DR now says most of the ~30 are Windows-gated and **names the two classes that are not**, pointing at §1. |
| B2 | §4's "nothing else required" contradicts §2.2/§2.3 | **REVISED** | Rank-1 row now scopes it: *"Code cost: one character. Also needs the §2.3 doorbell switched on and the §2.2 placement rule — neither is code."* |
| B3 | TL;DR omits the §2.3 doorbell | **REVISED** | TL;DR rebuilt around **three** costs — one code fix, one *configuration* step, one placement rule — with the doorbell's "and switchboard cannot tell" said up top. |
| B4 | §2's heading omits half of §2 | **REVISED** | Now "a code fix, a config step, a correctness rule, setup, and hygiene". |
| B5 | §1's opening sentence is a predicate-less fragment | **REVISED** | Rewritten to "**Every blocker gated on a Windows-specific code path dissolves** — that is, anything behind …". |
| B6 | §2.4's "no step optional" list is short | **REVISED** | Added the Python-3.11 floor check (which can disqualify the distro outright) and `sb doctor`. |
| B7 | "~52 sites (F7b/F9/F10/F11/F12)" mis-attributes | **REVISED** | Now "26 (F9) + 26 (F12), plus F7b and the stdio pair F10/F11". |
| C1 | §2.4 says §3.7, symlink is §3.10 | **REVISED** | Fixed; now agrees with §6. |
| C2 | Two paths resolve from the wrong directory | **REVISED** | Both prefixed `windows-support/`. |
| C3 | Appendix calls `review/` native-only | **REVISED** | Now describes both reviews, names the four WSL2 rounds, and warns about C4's trap. |
| C4 | Native-review files name this plan as their artifact | **REVISED** | All five headers corrected to `windows-support/native-port-plan.md`, each with a dated note saying what moved and that they did **not** review the WSL2 plan. |
| C5 | [W]/[L] dropped for steps 14–17; stray `[W-ish]` | **REVISED** | Markers restored on all four; step 15 (`wsl --shutdown`, sleep) correctly marked **[W]**; `[W-ish]` removed. |
| D1 | "Ubuntu 24.04 is what `wsl --install` gives you" is inferred | **REVISED** | Added to §6, stated as load-bearing — it is the whole reason §2.1 is required rather than optional — and noted as Microsoft behaviour that **has changed before**. |
| D2 | The distro/Python/lsof interaction is a support-matrix decision buried in a setup step | **REVISED** | Promoted into **§5** as a two-row table: 22.04 is **disqualified** on Python 3.10; 24.04 + the §2.1 fix is the supported target; **no combination needs neither**. The distro-version facts added to §6. |
| D3 | "A fresh box is clean" is asserted, not sourced | **REVISED** | Added to §6 as an assumption about herdr's *installer*, distinguished from `herdr.check()`'s refusal, which is verified. |
| F | Is `sb init` a missing step? | **CHECKED — it is not** | Verified: `store.main_checkout()` falls back to inferring from `.git`'s common dir when nothing is pinned (`store.py:122-132`), and `_refuse_outside_main_checkout` *skips* rather than guesses when it cannot establish one (`broker.py:1203-1221`). `sb start` works on an ordinary clone without it. §3 step 13 now says so, and says why running it once is still worth it (pins `main_checkout` instead of inferring it; keeps local config out of `git status`). §2.4's list is therefore not short by one. |

## Closing note on four rounds

The recommendation — run switchboard in WSL2 — was never attacked, in any round, by any reviewer.
What each round took was a comfort the plan had not earned:

- **R1:** "zero code changes" → F1 is measured broken on the default distro.
- **R2:** "setup is just installs" → the doorbell needs configuring, and fails invisibly.
- **R3:** "the deliverable is mostly a setup guide" → §3 was an outline; it is now a guide.
- **R4:** "the evidence supports this" → it did not; three cited docs asserted retracted claims.

Two things remain outstanding and are **not** review findings, both flagged upward rather than
fixed here: the §2.1 `-F pcnf` fix has to land in the repo, and `scripts/00-preflight.sh:26` still
tells readers to install the herdr `claude` integration that `herdr.py:320-335` refuses to start
with.
