# Model selection: what switchboard uses, what it should use

Answers the brief in `notes/model-selection-brief.md`. Three scouts: the model
landscape and cost (`notes/scratch-model-landscape.md`), community sentiment
(`notes/scratch-model-sentiment.md`), and what this repo actually does today
(`notes/scratch-current-models.md`). Detail and file:line citations live in those.

Dated 2026-08-16. Opus 5 is three weeks old, so all sentiment here is fresh and unsettled.

## The models, briefly

| Model | id | $/MTok in/out | ~$ per agent task | What it is for |
|---|---|---|---|---|
| Fable 5 | `claude-fable-5` | $10 / $50 | $1.40–4.40 | Hardest reasoning, longest autonomous runs. Slow. Runs until stopped. |
| Opus 5 | `claude-opus-5` | $5 / $25 | $0.70–2.20 | Anthropic's default for agentic coding. Thinking on by default. Chattiest of the family. |
| Opus 4.8 | `claude-opus-4-8` | $5 / $25 | $0.70–2.20 | Previous flagship, same price. Terser than 5. Under-reaches for subagents/search. |
| Opus 4.7 / 4.6 | `claude-opus-4-7` / `-4-6` | $5 / $25 | $0.70–2.20 | Older. No reason to pick over 4.8 except pinning. |
| Sonnet 5 | `claude-sonnet-5` | $2 / $10 | $0.30–0.90 | Prior-Opus-tier quality at ~2.5x less. Full effort ladder. |
| Haiku 4.5 | `claude-haiku-4-5-20251001` | $1 / $5 | $0.15–0.45 | Cheapest. Not a like-for-like substitute; also its permission classifier stalls unattended agents. |

All eight are active, none retired. All four Opus variants cost exactly the same —
choosing between them is a behaviour choice, never a cost one.

Task-cost figures assume 150k–500k input / 20k–60k output with ~80% cache reads.
That cache ratio is our own modelling assumption, not an Anthropic number.

One open question: Sonnet 5 shows $2/$10 live, but cached docs call that an intro rate
reverting to $3/$15 after 2026-08-31. Unresolved — worth a console check.

## What switchboard does today

Roles name a *tier*, not a model. `defaults/models.toml` is the only file where a
model name appears.

- `cheap` → `--model sonnet --effort medium`
- `default` → **nothing passed at all** — whatever the Claude Code CLI itself defaults to
- `strong` → `--model opus --effort high` — **used by no shipped role**

So: **researcher is on Sonnet 5. Everything else is unpinned**, riding the CLI's own
default (currently Sonnet 5 in observed sessions). Nobody is on Opus by default, anywhere.

Overriding is possible per-role (`.switchboard/roles.toml`) or per-call
(`sb delegate --model <tier>`); an unknown tier name passes straight through as a
literal model id, so `--model claude-opus-4-8` already works today.

## The table

"Best" = what the work actually needs, on capability. "Reddit" = what the community
would pick, weighted toward your dislike of Opus 5's style.

| Role / task | Current | Best (capability) | Preferred (Reddit / style) | Recommendation |
|---|---|---|---|---|
| **dispatcher** — route an ask to lead or worker | CLI default (Sonnet 5) | Sonnet 5 | no view | **keep** — one small decision, no reason to pay Opus |
| **lead** — split work, synthesise, write to humans | CLI default (Sonnet 5) | Opus 5 | **Opus 4.8** | **Opus 4.8, high** — leads write the prose you read; this is where the style complaint bites |
| **worker** — implementation | CLI default (Sonnet 5) | Opus 5, xhigh | **Opus 4.8** (contested) | **Opus 5, xhigh** — its output is code, not prose; style matters least here |
| **researcher / scout** — read, map, report | Sonnet 5, medium | Sonnet 5 | no view | **keep**, bump to high effort for a first scout |
| **reviewer** — read work, give a verdict | CLI default (Sonnet 5) | Opus 5, high | Opus 5 | **Opus 5, high** — the one thing the community rates Opus 5 above 4.8 at is diagnosing |
| **qa** — does the thing actually work | CLI default (Sonnet 5) | Sonnet 5, high | no view | **Sonnet 5, high** — tool-driven verification, not deep reasoning |
| **adversarial review** (a procedure a lead runs) | inherits reviewer/CLI default | Fable 5 | Fable 5 | **Opus 5 reviewers; Fable 5 only when they deadlock** — 2x price, and it runs until stopped |
| **summarisation** (`sb done`) | whoever wrote it | n/a | n/a | not separable — it rides the agent's own model |

## What the community actually says

The output-style complaint is real and broad, not a fringe view. Within a week of
Opus 5's launch the community had coined "Claudeslop" for its verbosity, hedging and
apology loops, with a circulating catalogue of tics: "load-bearing", em-dashes,
"worth stating plainly", "full stop", "isn't just X — it's Y". People report rolling
back to Opus 4.8 or 4.6, or paying up for Fable 5, specifically to escape it.

Two things worth acting on:

- **Generic "be concise" reportedly does not work.** What works is naming the specific
  tics. Anthropic's own guidance agrees on the mechanism: lowering effort does not
  shorten Opus 5's output, only an explicit brevity instruction does (~20% in their
  testing).
- **Remove "double-check your work" phrasing.** On Opus 5 that makes it worse — it
  already over-verifies. Good advice on older models, inverted here.

Both are prompt changes, not model changes, and both are cheap.

Coding quality is genuinely split: Opus 5 is praised for long unattended runs and bug
diagnosis, but a repeated counter-claim is that it is "a clear step down from 4.8 at
implementing" and burns roughly twice the tokens for the same task. A real minority
holds that 4.6 was the last good model. Nobody has settled this yet.

Sentiment on Sonnet 5 and Haiku 4.5 is thin — the cost-conscious crowd has not weighed
in post-launch. Treat the Sonnet recommendations above as reasoning from capability and
price, not as community consensus.

## Two gaps found on the way

Reported, not fixed — neither was in scope.

1. **`sb restore` drops a per-call `--model` override.** It re-resolves the tier from
   the agent's role alone, so an agent spawned `--model strong` comes back on its role's
   plain tier (`switchboard/broker.py:4643-4648`).
2. **The `default` tier pins nothing**, so five of six roles follow whatever the Claude
   Code CLI decides its default is — which can change under you without any switchboard
   change. That is deliberate per the config comment, but it does mean switchboard cannot
   answer "what model is my fleet on".

## What this costs

Moving lead, worker and reviewer off the unpinned default onto Opus-tier takes those
agents from roughly $0.30–0.90 to $0.70–2.20 per task — call it 2.5x on the agents that
do the heavy work, unchanged on dispatcher, researcher and qa. Fable 5 anywhere doubles
Opus again, which is why it is a deadlock escape hatch and not a default.
