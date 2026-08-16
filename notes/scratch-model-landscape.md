# Claude model landscape and cost — research notes

Sources: bundled `claude-api` skill (cached 2026-06-24) cross-checked against live docs fetched today (2026-08-16):
`platform.claude.com/docs/en/about-claude/models/overview.md` and `.../about-claude/model-deprecations`.
Pricing page (`/docs/en/pricing.md`) 404'd, so pricing comes from the models-overview table instead.

## Where the skill and the live docs disagree

1. **Sonnet 5 pricing.** The skill's cached table says $3.00/$15.00 per MTok standard, with a **$2.00/$10.00 "intro" rate through 2026-08-31**. The live models-overview page (fetched today) shows flatly **$2 / $10 per MTok** with no mention of an intro window or a future increase. Today (2026-08-16) is still inside the stated intro window, so I can't tell from this page alone whether:
   - the intro rate is what's live right now and will jump to $3/$15 after 2026-08-31 (skill's version), or
   - Anthropic made $2/$10 the permanent price and the "intro" framing is gone.
   **Treat $2/$10 as the current, billable rate; budget for a possible jump to $3/$15 after 2026-08-31 if you have anything running past that date.** I did not find a page that discusses the intro-rate expiry explicitly.
2. Everything else checked out: Fable 5 ($10/$50), Opus 5 ($5/$25), Opus 4.8/4.7/4.6 (all $5/$25 — flat across that whole Opus 4.x line), Haiku 4.5 ($1/$5), Sonnet 4.6 ($3/$15) all match between skill and live docs.
3. Model-deprecations page confirms all 8 requested models are **Active** with no retirement scheduled (see table below) — the skill didn't overstate or understate any of this.
4. New info not in the skill: reliable **knowledge cutoffs** (below) and a Batch-API detail — Opus 5/4.8/4.7/4.6 and Sonnet 5/4.6 support up to 300k output tokens on the Batches API via beta header `output-300k-2026-03-24` (vs 128k normally). Not verified beyond what the page states.

## Per-model summary

| Model | Model ID | Status (per model-deprecations, checked live) | Input $/MTok | Output $/MTok | Context | Max output | Reliable knowledge cutoff |
|---|---|---|---|---|---|---|---|
| **Opus 5** | `claude-opus-5` | Active, retirement "not sooner than Jul 24, 2027" | $5 | $25 | 1M | 128K | May 2026 |
| **Opus 4.8** | `claude-opus-4-8` | Active, "not sooner than May 28, 2027" | $5 | $25 | 1M | 128K | Jan 2026 |
| **Opus 4.7** | `claude-opus-4-7` | Active, "not sooner than Apr 16, 2027" | $5 | $25 | 1M | 128K | Jan 2026 |
| **Opus 4.6** | `claude-opus-4-6` | Active, "not sooner than Feb 5, 2027" | $5 | $25 | 1M | 128K | May 2025 |
| **Fable 5** | `claude-fable-5` | Active, "not sooner than Jun 9, 2027" | $10 | $50 | 1M | 128K | Jan 2026 |
| **Sonnet 5** | `claude-sonnet-5` | Active, "not sooner than Jun 30, 2027" | $2* | $10* | 1M | 128K | Jan 2026 |
| **Sonnet 4.5** | `claude-sonnet-4-5-20250929` (alias `claude-sonnet-4-5`) | Active, "not sooner than Sep 29, 2026" | $3 | $15 | 200K | 64K | Jan 2025 |
| **Haiku 4.5** | `claude-haiku-4-5-20251001` (alias `claude-haiku-4-5`) | Active, "not sooner than Oct 15, 2026" | $1 | $5 | 200K | 64K | Feb 2025 |

\* See the discrepancy note above — this may be a temporary intro rate that reverts to $3/$15 after 2026-08-31.

None of these 8 are deprecated or scheduled for retirement. (For context: Opus 4.1 *was* deprecated and is now actually retired as of Aug 5, 2026 — already past, not just "coming soon" — but that's not one of the 8 you asked about.)

## What each is good/bad at

**Opus 5** (`claude-opus-5`) — Anthropic's recommended default for "complex agentic coding and enterprise work." Strongest of the eight on hard, long-horizon coding and agentic tasks (multi-file refactors, end-to-end features); weakest differentiation on short single-turn edits. Thinking is **on by default** (a change from 4.8/4.7, where it was off unless requested) — full effort ladder low→max, with `xhigh` recommended as the sweet spot for coding/agentic work. High-res vision (2576px), 1M context as both default and ceiling, strong multi-agent delegation (arguably *too* eager — it delegates to subagents more than Opus 4.8 did, worth capping in a harness). Elevated cybersecurity safeguards mean it can return `stop_reason: "refusal"` on benign security-adjacent work — plan for that. Bad/watch-outs: **longer default output than 4.8** — both conversational replies and files it writes to disk are verbose unless you add explicit conciseness instructions; it also over-verifies its own work unless you strip out verification-prompting you may have inherited from an older model's prompt.

**Opus 4.8** (`claude-opus-4-8`) — previous flagship, still fully active. Best-in-class (at the time) for long-horizon agentic execution and knowledge work; writing is described as clearer/warmer/less hedged than 4.7. Thinking is off unless you explicitly request adaptive thinking. Tends to *under*-reach for subagents, file-based memory, and search — needs explicit "when to use this" prompting to get full value from delegation and search tools. More deliberate than newer models — asks permission on small decisions more than users often want; that's tunable with an explicit "just decide" instruction.

**Opus 4.7** — one generation older; adaptive thinking is off by default (must opt in), no sampling params, no prefill. More literal instruction-following than 4.6, calibrates verbosity to task complexity, uses tools less by default than 4.6 (recoverable by raising `effort` or adding explicit trigger language in tool descriptions). High-res vision was new here. Good target if you specifically need to stay one rung below the current flagship for cost/stability reasons, but there's no strong reason to pick it over 4.8/5 today.

**Opus 4.6** — oldest of the four Opus variants asked about. Still supports the older `budget_tokens` extended-thinking mechanism as a functional-but-deprecated escape hatch (blocked on 4.7+). Adaptive thinking recommended. Most "overtriggering" issues (aggressive tool use from CRITICAL/MUST-style prompts) are specific to this generation and 4.5 — prompts written for 4.6 often need toning down to work well on 4.7+.

**Fable 5** (`claude-fable-5`) — Anthropic's most capable model overall, positioned above Opus 5, priced at double Opus 5's rate. Thinking is **always on** (can't be disabled — explicit `disabled` 400s). Best for the hardest reasoning and the longest-horizon autonomous agent runs — individual requests can legitimately run many minutes; not designed for latency-sensitive interactive use. Strongest reported gains: end-to-end enterprise deliverables (financial models, decks, docs), dense/degraded-image vision, sustained multi-agent delegation, code review/debugging (excluding security-focused analysis). Raw chain-of-thought is never exposed even with `display: "summarized"` — you get a summary, never the real trace. Requires 30-day data retention (unavailable under zero-data-retention orgs — hard 400 if your org doesn't meet that). Not the default upgrade path — only pick it when the task genuinely needs the top tier; Opus 5 remains Anthropic's suggested general-purpose flagship.

**Sonnet 5** (`claude-sonnet-5`) — "best combination of speed and intelligence," reaching prior Opus-tier quality on coding/agentic work at a fraction of the price. Full effort ladder including `xhigh` (first Sonnet-tier model with it). Thinking on by default (adaptive), unlike Sonnet 4.6 where omitting `thinking` meant no thinking at all — this is a real behavioral trap when migrating: a `max_tokens` sized tightly around a thinking-off Sonnet-4.6 workload can silently truncate on Sonnet 5. New tokenizer vs 4.6 (~30% more tokens for the same text) — re-baseline any token-based budgets. Weaker with thinking disabled: less likely to reach for tools.

**Sonnet 4.5** — a full generation behind Sonnet 5/4.6 on the "current" ladder (it's in the "legacy, still active" bucket) but still fully supported. No adaptive thinking, no `effort` parameter beyond low/medium/high (no xhigh/max) — Sonnet 4.5 predates the effort-parameter API entirely on some surfaces. 200K context, 64K max output (vs 1M/128K on the newer Sonnet models) — a meaningfully smaller ceiling. Reasonable choice only if you're pinned to it for reproducibility/regression reasons; Sonnet 5 outperforms it on coding/agentic work for a lower headline price right now (see pricing caveat above).

**Haiku 4.5** — fastest, cheapest, "near-frontier intelligence" per Anthropic's own framing, but genuinely a smaller/faster tier: 200K context, 64K max output (all others in this list except Sonnet 4.5 get 128K). Supports classic extended thinking (`budget_tokens`) rather than adaptive thinking — it's the one model here still on the old thinking mechanism. Best for simple/fast/cheap tasks: classification, short lookups, latency-sensitive endpoints, or as a cheap subagent/worker model spawned by a larger coordinator (this is an explicitly recommended pattern in Anthropic's multiagent docs — pair a Sonnet/Opus coordinator with Haiku 4.5 workers for reading-heavy, low-reasoning subtasks).

## Output style and verbosity — Opus 5 vs Opus 4.x vs Fable 5

This is the most concrete, well-documented behavioral delta across the family, straight from Anthropic's own migration guidance (not third-party benchmarking):

- **Opus 4.7 → 4.8**: 4.8 writes *more* narration between tool calls and longer end-of-task wrap-ups than 4.7 by default (4.7 was comparatively terse/direct). If your harness had scaffolding forcing periodic progress updates for 4.7, remove it on 4.8 — it self-narrates now.
- **Opus 4.8 → Opus 5**: verbosity increases again, on two axes — conversational response length **and** the length of files/documents Opus 5 writes to disk. Anthropic's own guidance: lowering `effort` does *not* reliably shorten Opus 5's visible output (effort controls thinking depth, not response length) — you need an explicit conciseness instruction in the prompt to pull it back (~20% length reduction measured in Anthropic's testing). Opus 5 also over-verifies its own work by default — remove any "double-check your answer" style instructions carried over from older models; on Opus 5 that phrasing makes it worse, inverting what's normally good prompting advice on older models.
- **Fable 5**: verbose in a different way — not chatty small talk, but a tendency toward long, comprehensively-structured writing (structured PR descriptions, sections on rejected alternatives, comments narrating obvious code) when un-steered, especially at higher `effort`. Anthropic recommends a short "lead with the outcome, don't over-explain" instruction. Turns are also structurally longer in wall-clock time — a 15-minute single request is described as "normal" for Fable 5 on hard tasks, which is a different kind of "verbosity" (time, not necessarily token count) than the Opus-line story.

Net effect: **each newer model in the Opus line got chattier by default**, not quieter, and the fix each time is the same lever — an explicit brevity/no-self-verification instruction in the system prompt — not a lower effort setting.

## Ballpark cost of one "average agent task"

**Stated assumptions** (yours, from the task): 150K–500K input tokens (with prompt caching in play), 20K–60K output tokens. I computed two bounds:

- **No caching** (full sticker price on every input token) — worst case, e.g. first run of a session or a cache-hostile prompt.
- **With caching** — I assumed roughly 80% of the reported input tokens are cache reads (billed at ~0.1× input price) and 20% are fresh/full-price, which is a plausible shape for a multi-turn coding-agent loop that keeps re-sending a large, mostly-unchanged context (system prompt, file contents, tool definitions). This is **my own modeling assumption, not something Anthropic states as typical** — real cache-hit ratios vary a lot by how the harness is built (see `shared/prompt-caching.md` in the skill for what actually drives the ratio).

All figures in USD, at the model's *current* listed price (Sonnet 5 at the $2/$10 rate — see caveat above).

| Model | Low end (150K in / 20K out), no cache | Low end, cached (~80% reads) | High end (500K in / 60K out), no cache | High end, cached (~80% reads) |
|---|---|---|---|---|
| Fable 5 ($10/$50) | $2.50 | ~$1.42 | $8.00 | ~$4.40 |
| Opus 5 / 4.8 / 4.7 / 4.6 ($5/$25, all identical) | $1.25 | ~$0.71 | $4.00 | ~$2.20 |
| Sonnet 5 ($2/$10 current) | $0.50 | ~$0.28 | $1.60 | ~$0.88 |
| Sonnet 5 (if it reverts to $3/$15) | $0.75 | ~$0.43 | $2.40 | ~$1.32 |
| Sonnet 4.5 ($3/$15) | $0.75 | ~$0.43 | $2.40 | ~$1.32 |
| Haiku 4.5 ($1/$5) | $0.25 | ~$0.14 | $0.80 | ~$0.44 |

Reading this: a typical coding-agent task on Opus-tier (5/4.8/4.7/4.6 — they're all priced identically) costs somewhere around **$0.70–$2.20** with realistic caching, or up to $4 uncached at the high end of the token range. The same task on Sonnet 5 at today's rate is roughly **2.5× cheaper** than Opus-tier; Fable 5 is roughly **2× more expensive** than Opus-tier; Haiku 4.5 is the cheapest by a wide margin but is a materially less capable model, not a drop-in substitute for coding-agent work at Opus/Sonnet quality.

## Confidence and caveats

- Model IDs, active/deprecated/retired status, and 7 of 8 prices are **directly confirmed against live Anthropic docs fetched today** (high confidence).
- The Sonnet 5 $2/$10-vs-$3/$15 question is **unresolved** — flagged above, not something I could settle from the pages I fetched. If this matters for planning, worth a direct check of the console billing page or Anthropic's pricing announcement rather than trusting either source blindly.
- The 80%-cache-hit-ratio cost model is **my assumption**, not an Anthropic-stated benchmark — treat the "with caching" cost column as illustrative, not a guarantee. Real ratios depend heavily on how the harness structures its prompts (see the skill's prompt-caching guidance for what actually helps/hurts cache hit rate).
- I did not independently load-test or benchmark speed/quality claims — the "good at / bad at" summaries above are Anthropic's own stated positioning and migration-guide behavioral notes, not my own evaluation.
