# Quant/systematic hedge fund gap research

Assignment: BRIEF-QUANT-GAP.md — find systematic/multi-strategy hedge funds and
quant asset managers not among the 36 already covered in
`/Users/andrew/Code/recruiting/roles/quant-swe.csv`, that pay new-grad SWEs
$250K+ but do little/no campus marketing. Output written to
`/Users/andrew/Code/recruiting/roles/quant-gap-funds.csv` (44 rows).

## Method

Fanned out 6 parallel general-purpose subagents, each with WebSearch/WebFetch,
covering ~35 named candidate firms from the brief plus a systematic
enumeration pass (H1B/LCA data via h1bdata.info, levels.fyi, Glassdoor,
r/quant / r/csMajors / Blind threads, university career-center listings,
Built In Chicago). Each agent was told to verify every URL before reporting
it and to say "unknown" rather than invent one. I did not independently
re-fetch every URL myself — I'm relying on each subagent's verification
claims (they used WebFetch and reported "resolves" or "404s" explicitly).
Where an agent didn't verify a URL (e.g. Geneva Trading, Spark, Coatue's real
internal board), I recorded `unknown` in the CSV rather than trust an
unverified guess.

## Firms with real signal, ranked (see CSV for full detail)

1. **Voleon** — confirmed to have run an annual "University Hire" new-grad
   SWE cycle (2026 cohort posting now closed); ~$300-328K per levels.fyi.
   Public ATS, not referral-gated. Strongest hit.
2. **PDT Partners** — new-grad SWE hiring exists but only converts from a
   junior-year internship; ~$400-462K estimate (levels.fyi). That
   internship window has already passed for this cycle.
3. **Global Trading Systems (GTS)** — real in-house engineering (NYSE
   Designated Market Maker), ~$250K levels.fyi median, hires new grads via
   an intern/co-op pipeline, minimal public marketing for the pay level.
4. **ExodusPoint** — has a dedicated "Campus" Greenhouse board
   (job-boards.greenhouse.io/xpcampus) and a rotational tech program; best
   new-grad structural signal of the multi-strategy pod shops, but current
   board is thin.
5. **Renaissance Technologies** — publicly posts bachelor's-eligible
   Programmer roles (Data/Infra/Research Infrastructure), not labeled "new
   grad" but open to them; near-zero marketing, legendary pay reputation,
   base $160-227K+ per H1B (total comp likely materially higher).

Also promising but weaker/unclear evidence: Geneva Trading (Chicago, $218-317K
per levels.fyi, but I could not verify a careers URL), Schonfeld, WorldQuant,
Arrowstreet Capital (historical SWE rotational program, not just quant
research), Freestone Grove, Tudor Investment.

## Clear misses worth noting explicitly (per brief's instruction that this is
useful information)

- **Firms with real, public new-grad SWE programs but comp well under
  $250K**: Man Group US/Man Numeric Boston ($85-100K base — the *only*
  firm in this batch with a confirmed, currently-postable new-grad SWE
  rotational program), BlackRock SAE, Fidelity LEAP, Wellington TAP,
  T. Rowe Price Associate SWE, Graham Capital Management. These are real
  engineering orgs that do recruit new grads, they just don't clear the
  candidate's comp bar.
- **Extreme pay, but no evidence of any new-grad hiring / likely
  referral-only**: TGS Management (board currently empty, tiny/secretive,
  no evidence of ever running a new-grad program), Symmetry Investments
  (known for hiring engineers via unconventional-language reputation, not
  campus recruiting), Verition (all live postings senior/experienced),
  Kirkoswald Capital (no public careers page at all), Element Capital
  Management (no public careers page, apply via email only), Hudson Bay
  Capital (zero postings, email-only), Coatue Management (internal
  engineering hiring is opaque — `jobs.coatue.com` is a portfolio-company
  aggregator, not Coatue's own board, and no genuine internal careers URL
  could be found).
- **No real US office / not viable for a US new-grad candidate**: Dymon
  Asia (zero Americas offices, confirmed via their own contact page),
  Astaris Capital Management (UK-only, Blackstone-backed credit fund, no
  US presence found), Brevan Howard (careers taxonomy doesn't even list
  software engineering as a category), Winton (live board shows zero US
  openings), Rokos and Capula (both have real graduate tech programs, but
  they're explicitly London-based; their NY offices only take speculative
  applications).
- **Not a real ongoing recruiting target**: Weiss Multi-Strategy Advisers
  — the firm shut down and filed Chapter 11 in 2024 (confirmed via
  Bloomberg reporting); excluded entirely from the CSV rather than listed
  as a row, since there is no firm left to apply to.
- **Could not verify the firm exists at all**: "Angstrom Capital" — no
  subagent could find a hedge fund by this name; searches only surfaced
  unrelated entities (an engineering firm, a sports-betting data company,
  a small Austin RIA, a BVI shell). Excluded from the CSV. Recommend
  double-checking the exact name with whoever supplied the candidate list.

## Categories checked with essentially nothing found

- Technology arms of large traditional asset managers (BlackRock, Fidelity,
  Wellington, PGIM, T. Rowe Price) — real engineering orgs, real new-grad
  pipelines, but comp consistently well under $250K. PGIM Quantitative
  Solutions specifically showed no clear dedicated new-grad SWE pipeline at
  all.
- Macro hedge funds with UK/European HQs and thin US new-grad presence
  (Rokos, Capula, Brevan Howard, Element Capital, Winton, Systematica,
  Dymon Asia).
- Small/inactive prop-adjacent shops with too little signal to be useful
  leads: Fort Investment Management (~60 employees, careers page nearly
  empty), GSA Capital's US office (real engineering is UK-based), Domeyard
  (wants 5+ yrs C++, not new-grad friendly), Group One Trading (SWE
  internship exists but live postings skew trading-analyst, not SWE).
- Enumeration pass (H1B/LCA + Blind/Reddit threads) surfaced mostly firms
  already on the 36-firm exclusion list rather than genuinely new names —
  yield was modest. The strongest new names it produced were GTS and
  Geneva Trading (both included above), plus weaker leads Spark Investment
  Management, Ansatz Capital, and Eagle Seven (all included in the CSV,
  ranked lower, with the caveat that new-grad-specific data is thin).

## Caveats

- Comp figures are frequently based on small H1B/LCA samples (as few as
  3-5 records) or on levels.fyi self-reports that may skew toward
  experienced hires rather than true new-grad total comp. Every row's
  `evidence` column names the source; treat single-digit-sample figures as
  directional only.
- I did not personally re-verify every URL a subagent reported as
  "resolves" — I trusted their WebFetch-based checks. Where a subagent's
  own report showed the URL as unverified or the agent didn't attempt a
  fetch, I used `unknown` rather than propagate an unconfirmed link.
