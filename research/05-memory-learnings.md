# 05 — Agent Memory & the Learnings Store

Research: should we adopt an existing agent-memory system, fork one, or build a small
purpose-built MCP server for the learnings store (and the companion todo store)?

Date: 2026-08-06

---

## TL;DR — Recommendation

**Build. A small, purpose-built, local-first MCP server. Do not adopt any of the
agent-memory platforms. Do not fork one either — but steal two specific designs.**

The entire agent-memory category (mem0, Letta, Zep, Cognee, Supermemory, Memobase,
MemoryOS, A-MEM, Cipher, LangMem…) is built around a problem we do not have. They are
solving **"the user said something 40 sessions ago and the agent should recall it"** — a
recall problem, addressed with embeddings, extraction LLMs, and vector stores. Our
problem is **"at step N of a known workflow, inject the curated rules that apply to step
N"** — a *dispatch* problem, addressed with an index lookup on a label set. These are
different products that happen to share the word "memory."

Concretely, adopting any of them costs us:

- an embedding model and/or an LLM call on every write (mem0, Zep, Cognee, MemoryOS,
  A-MEM, claude-mem all extract/summarize with an LLM at write time),
- a vector DB or graph DB as a runtime dependency,
- non-deterministic retrieval — `search("pre-merge")` returns *approximately* the right
  learnings, ranked, with a similarity floor. Our requirement is "give me exactly the
  learnings labeled `pre-merge`," which is `WHERE tag = ?`. A vector store makes that
  *harder*, not easier,
- an opaque storage format that fights the braindump's principle #2 ("everything is data,
  not prose" — renderable by any UI),
- and 4–8 extra tool schemas in every agent's context (~1k tokens per MCP tool
  definition), which is exactly the context bloat we're trying to escape.

Two findings clinch it. **First:** across all fourteen systems surveyed, only *two* —
mem0's `get_all(filters=…)` and Supermemory's `/v3/documents/list` — let you retrieve by
label with **no query string at all**. Every graph system requires one. Our primary
access pattern is the one the category doesn't support. **Second:** the churn is brutal —
Zep Community Edition deprecated, OpenMemory MCP deprecated, `mem0ai/mem0-mcp` archived,
Supermemory's `containerTags` deprecated, mem0 v1.0 breaking auth changes, all within ~18
months. This should be boring infrastructure we never think about, not a dependency that
forces a migration every other quarter.

The build is genuinely small: SQLite + a JSON row shape + 4 tools. A weekend, not a
quarter. The scope risk of adopting mem0/Letta is far higher than the scope risk of
writing ~600 lines.

**Two things to steal rather than invent:**

1. **CodeRabbit's learnings product design** (not code — it's closed). It is the closest
   shipping thing to what we want, and it validates the whole shape: natural-language
   learnings, created from review feedback, scoped, stored with provenance metadata (PR
   number, file, author, timestamp, **usage count**), a curation dashboard where a human
   edits or deletes them, CSV export/import, and an optional **approval workflow** that
   delays application of new learnings. Copy the metadata set and the curation loop
   wholesale.
2. **ExpeL's insight-pool write operations** (ADD / EDIT / UPVOTE / DOWNVOTE with an
   importance counter). This is the academic answer to "how do you stop a learnings store
   from rotting" and it costs almost nothing to implement.

**Also steal, secondarily:** Redis Agent Memory Server's *filter algebra* (`eq`, `ne`,
`any`, `all`, `in` over tag fields) — good prior art for the shape of a label query,
even though we won't use Redis.

**Do not build:** a second retrieval mode. Ship labels-only. Add lexical (FTS5) search as
a fallback in v1.1 only if agents demonstrably fail to find things. Do not add embeddings
until you have evidence you need them — see §3.

---

## Proposed tool surface (the deliverable)

Design constraints that drove this:

- **Tool count is a context tax.** MCP tool definitions cost ~1k tokens each; a 58-tool
  setup measured at ~55k tokens before the conversation starts. Anthropic's own numbers
  put unoptimized tool definitions at up to 134k tokens. So: **4 tools for learnings, 3
  for todos, and that's the budget.** Resist a tool per operation.
- **Both Claude Code and Codex must work.** That means: stdio transport, tools only, no
  reliance on MCP resources/prompts/elicitation (see §7).
- **Every response must be small and pre-organized**, because the whole point is to spend
  fewer tokens than a markdown file would.

### `learnings_get` — the hot path

The tool agents call constantly. Optimize its ergonomics above all else.

```jsonc
// input
{
  "labels": ["pre-merge", "p0"],      // required, non-empty
  "match": "any",                      // "any" (default) | "all"
  "limit": 20,                         // default 20, max 100
  "min_confidence": "provisional",     // "provisional" (default) | "accepted"
  "format": "compact"                  // "compact" (default) | "full"
}
```

```jsonc
// output — grouped by label, not a flat list. Grouping is the "organized" in the spec.
{
  "matched": 7,
  "returned": 7,
  "truncated": false,
  "groups": [
    {
      "label": "pre-merge",
      "learnings": [
        { "id": "lrn_01J8Z…", "text": "Run `pnpm typecheck` before merging; CI does not run it on draft PRs.", "labels": ["pre-merge", "ci"], "score": 7 }
      ]
    },
    {
      "label": "p0",
      "learnings": [ /* … */ ]
    }
  ],
  "unmatched_labels": ["p0"],          // labels you asked for that have no learnings
  "suggested_labels": ["merge-conflict"] // co-occurring labels — cheap discovery
}
```

Notes on why:

- **Grouped by label** in the response. The braindump says "get back the relevant
  learnings, *organized*." Grouping by the label that matched them is the organization,
  and it also teaches the agent the taxonomy implicitly.
- `compact` omits `provenance`, `created_at`, `source_run`. Agents almost never need
  them; a human curation UI reads the store directly (or via `learnings_search`).
- A learning matching two requested labels appears **once**, under its highest-scoring
  match, with its full `labels` array present — no duplication, no wasted tokens.
- `unmatched_labels` is a quiet signal that your taxonomy has drifted.
- `min_confidence` lets autosaved (unreviewed) learnings be excluded from high-stakes
  steps. This is CodeRabbit's approval-delay idea, made explicit.

### `learnings_add`

```jsonc
// input
{
  "text": "Run `pnpm typecheck` before merging; CI does not run it on draft PRs.",
  "labels": ["pre-merge", "ci"],
  "scope": "repo",                     // "repo" (default) | "user" | "global"
  "confidence": "provisional",         // autosave writes provisional; humans write accepted
  "supersedes": "lrn_01J8Y…",          // optional — explicit contradiction handling
  "provenance": {                      // optional, agent fills what it knows
    "run_id": "wf_1234",
    "template": "fix-bug",
    "step": "pre-merge",
    "repo": "acme/api",
    "files": ["src/db/migrate.ts"],
    "pr": 481
  }
}
```

```jsonc
// output
{ "id": "lrn_01J8Z…", "status": "created", "near_duplicates": [
  { "id": "lrn_01J7Q…", "text": "…", "similarity": "high" }
] }
```

`near_duplicates` is the single most important anti-rot feature. On write, do a cheap
lexical near-duplicate check (trigram / FTS5 over the same label set). If a duplicate
exists, **still create it** but return the collision, and let the agent decide to call
`learnings_update` with an `upvote` instead. Do not silently merge — silent merging is
how memory stores lose information.

### `learnings_update` — ExpeL's operations, one tool

```jsonc
// input
{
  "id": "lrn_01J8Z…",
  "op": "upvote",   // "upvote" | "downvote" | "edit" | "retire" | "relabel" | "promote"
  "text": "…",      // required for "edit"
  "labels": ["…"],  // required for "relabel"
  "reason": "Contradicted by the new CI config in #512"   // required for downvote/retire
}
```

- `upvote` / `downvote` adjust `score`. New learnings start at **score 2** (ExpeL's
  initial importance count). At **score ≤ 0** the learning is auto-retired (soft-deleted,
  still visible in the curation UI, excluded from `learnings_get`).
- `retire` is a soft delete. **Never hard-delete from a tool.** Hard delete is a
  human-only operation in the UI. An agent that can permanently destroy institutional
  knowledge is a liability, and retired learnings are the audit trail for why a rule
  stopped applying.
- `promote` moves `confidence: provisional → accepted`. Gate it: either humans-only, or
  allow an agent to promote only a learning it has used ≥ N times successfully.
- `reason` is mandatory on destructive ops. It goes in the history log. This is what makes
  the curation UI usable six months later.

### `learnings_labels` — taxonomy discovery

```jsonc
// input  { "prefix": "review/" }   // optional
// output
{
  "labels": [
    { "label": "pre-merge", "count": 12, "co_occurs_with": ["ci", "p0"] },
    { "label": "code-review", "count": 34, "co_occurs_with": ["style"] }
  ]
}
```

Cheap, and it prevents the #1 failure mode of any tag system: agents inventing
`premerge`, `pre_merge`, `PreMerge`, and `before-merge` as four separate labels. Put
"call `learnings_labels` before inventing a label" in the tool description of
`learnings_add`, and **reject unknown labels by default** (see label taxonomy below).

### Optional 5th tool — `learnings_search` (defer to v1.1)

Free-text lexical search (SQLite FTS5) over `text`, for when an agent doesn't know the
label. **Ship v1 without it.** Add it only if telemetry shows agents calling
`learnings_get` with labels that return nothing. Every tool you add is ~1k tokens on
every agent, forever.

---

## Stored learning — JSON schema

Storage: **SQLite** (one file per scope: `.agentflow/learnings.db` in-repo, plus
`~/.agentflow/learnings.db` for user scope). The physical layout is an implementation
detail per the braindump — SQLite gets us atomic concurrent writes from parallel agents
for free, which a JSON file or markdown file emphatically does not. Rows serialize to
the JSON below for export/UI; a `learnings export` command writes YAML/JSON for git
review if desired.

```jsonc
{
  "$schema": "https://agentflow.dev/schemas/learning/v1.json",
  "id": "lrn_01J8ZQ4K3M7X0T",          // ULID — sortable, no coordination needed
  "schema_version": 1,

  "text": "Run `pnpm typecheck` before merging; CI does not run it on draft PRs.",
  "labels": ["pre-merge", "ci", "p1"],

  "scope": "repo",                      // repo | user | global
  "confidence": "accepted",             // provisional | accepted
  "status": "active",                   // active | retired

  "score": 5,                           // ExpeL importance count; starts at 2
  "use_count": 23,                      // times returned by learnings_get
  "last_used_at": "2026-08-01T10:12:00Z",

  "created_at": "2026-06-02T09:14:00Z",
  "created_by": "agent:claude-code",    // or "human:andrew"
  "updated_at": "2026-07-30T11:02:00Z",

  "supersedes": ["lrn_01J7QF…"],        // explicit contradiction chain
  "superseded_by": null,

  "expires_at": null,                   // optional TTL for known-temporary knowledge

  "provenance": {
    "run_id": "wf_1234",
    "template": "fix-bug",
    "step": "pre-merge",
    "repo": "acme/api",
    "pr": 481,
    "files": ["src/db/migrate.ts"],
    "commit": "a1b2c3d"
  },

  "history": [                          // append-only audit for the curation UI
    { "at": "2026-07-30T11:02:00Z", "by": "human:andrew", "op": "edit", "reason": "narrowed to draft PRs" }
  ]
}
```

Fields earning their place:

- **`score` + `use_count` + `last_used_at`** — the three columns that let a curation UI
  answer "which learnings are load-bearing and which are dead weight." CodeRabbit stores
  usage stats for exactly this reason. Without them, curation is guesswork.
- **`supersedes` / `superseded_by`** — the direct fix for the documented "stacked
  contradictions" failure mode, where a store holds both "prefer verbose" and "prefer
  terse" and top-k retrieval surfaces both with no recency signal.
- **`expires_at`** — a lot of learnings are true *for now* ("the staging DB is down, skip
  integration tests"). An unexpiring store of such facts is actively harmful. Retrieval
  filters expired rows.
- **`confidence`** — the seam that makes autosave safe. Autosaved learnings land
  `provisional`; high-stakes steps ask for `min_confidence: "accepted"`.
- **`created_by`** — distinguishing agent-written from human-written learnings is the
  first thing a curator wants to filter on.

**Redaction on write** is non-negotiable: run a secret scanner on `text` before persist
and replace matches with type markers. CodeRabbit does exactly this
(`***REDACTED_GITHUB_TOKEN***`). Learnings get exported, shared, and committed; an agent
that pastes a token into a learning has just leaked it into a durable, replicated store.

---

## Label taxonomy design

**Verdict: flat strings with an optional `namespace/value` convention, from a closed
vocabulary defined in a config file, with a controlled escape hatch. Not hierarchical.**

Reasoning:

- **Not hierarchical.** True hierarchies (`review/security/authz`) force a decision at
  write time about where something "lives," and get that decision wrong constantly.
  Learnings are inherently multi-faceted: one learning is *both* `pre-merge` *and*
  `high-risk` *and* `database`. Faceted flat tags model that; a tree doesn't.
- **But namespaced by convention**, because pure flat tags collapse into mush at ~50
  labels. Use a `facet:value` (or `facet/value`) string form. The server treats it as an
  opaque string — no tree logic, no ancestor resolution — but the UI can group by prefix
  and `learnings_labels` can filter by prefix. You get 90% of hierarchy's ergonomics for
  0% of its complexity.

Proposed facets (ship these as the default vocabulary):

| Facet | Meaning | Example values |
|---|---|---|
| `step:` | Which workflow step this applies at | `step:pre-merge`, `step:code-review`, `step:plan`, `step:implement` |
| `risk:` | Severity / blast radius | `risk:p0`, `risk:p1`, `risk:high` |
| `area:` | Part of the system | `area:db`, `area:auth`, `area:ci`, `area:frontend` |
| `kind:` | What sort of knowledge | `kind:gotcha`, `kind:convention`, `kind:invariant`, `kind:workaround` |
| `lang:` | Language/stack | `lang:ts`, `lang:python` |

The user's examples map cleanly: `pre-merge → step:pre-merge`, `code-review →
step:code-review`, `p0 → risk:p0`, `high-risk → risk:high`.

**Accept bare labels too.** `learnings_get(labels: ["pre-merge"])` should match
`step:pre-merge`. Implement as: an unqualified label matches any facet's value. This
keeps the ergonomics identical to the braindump's example while allowing structure to
grow underneath. Zero cost, big usability win.

**Closed vocabulary by default.** `learnings_add` with an unknown label returns an error
listing the closest known labels, unless `allow_new_labels: true` is set in config or
passed explicitly. This is the difference between a taxonomy and a tag swamp. Every
uncontrolled tagging system in history has degenerated; agents are worse at this than
humans because they're stochastic. The vocabulary lives in
`.agentflow/labels.yaml` — data, per principle #2, editable by a human, renderable by the
UI:

```yaml
facets:
  step:
    values: [plan, design, implement, code-review, pre-merge, merge, manual-test]
  risk:
    values: [p0, p1, p2, high, low]
  area:
    values: [db, auth, ci, frontend, api]
    open: true      # this facet accepts new values without config change
```

**Crucially: bind labels to workflow steps, not to agent judgment.** The single highest-
leverage design decision here. A template step declares
`learnings: {labels: ["step:pre-merge", "risk:p0"]}`, and the runtime injects the result
of `learnings_get` into that step's prompt *automatically*. The agent doesn't have to
decide to call the tool or guess which labels apply — the workflow already knows. Devin's
knowledge base is the cautionary tale here: every entry needs a hand-written natural-
language "trigger description," and vague triggers mean knowledge surfaces at the wrong
time or not at all. Our templates give us the trigger for free, deterministically. **This
is the actual differentiator over every system surveyed.**

---

## Autosave learnings

Design it as a **capture-then-curate** pipeline, not a write-through:

1. **Capture** at run boundaries, not continuously. Claude Code hooks (`SessionEnd`,
   `PreCompact`, `Stop`) are the mechanism; claude-mem uses six hooks
   (SessionStart, UserPromptSubmit, PostToolUse, Stop, SessionEnd, plus an install hook)
   and is Apache-2.0 — read its hook wiring as reference. Codex has no equivalent hook
   surface (tool events there are limited, and PreToolUse/PostToolUse hooks don't cover
   MCP tool calls), so for Codex the capture point is **the controller**, not the agent:
   when a workflow step completes, the controller runs an extraction pass over the step's
   result. That's a better architecture anyway — it's uniform across backends, and it fits
   the braindump's "controller reads state, not transcripts."
2. **Extract** with a cheap model, prompted hard for specificity: a learning must be
   actionable, non-obvious, and generalizable beyond the current file. Most runs produce
   zero learnings; the extractor must be allowed — encouraged — to return `[]`. An
   extractor that always produces something will fill the store with "remember to read
   the code before editing it" inside two weeks.
3. **Land as `provisional`**, always. Never let an autosaved learning reach a `p0` step
   before a human sees it. CodeRabbit ships an optional approval workflow that delays
   application of new learnings by up to 30 days — that instinct is correct.
4. **Curate** in the UI. The inbox of provisional learnings *is* a first-class screen in
   the workflow status UI, alongside blocked workflows. Batch-promote, edit, relabel,
   discard.

Budget the store. A hard cap (say 500 active learnings per repo) with score-based
eviction is a feature, not a limitation. An unbounded learnings store is a slower, more
expensive CLAUDE.md.

---

## §1 — Survey of purpose-built agent memory systems

The single most useful column is "can you retrieve **with no query string at all**, purely
by label?" Almost nothing can.

| System | License | MCP? | Label/tag retrieval? | Local-first? | Weight |
|---|---|---|---|---|---|
| **mem0** | Apache-2.0 (~62.7k★, active). OSS is genuinely crippled vs platform: export ❌, decay ❌, temporal ❌, dashboard ❌, "Memory filters v2 ⚠️ via metadata only" | `mem0ai/mem0-mcp` **archived Mar 2026** (was cloud-key-only); OpenMemory MCP **deprecated** | **YES — best in class.** `get_all(filters=…)` is query-free filter listing. Operators `gt/gte/lt/lte/eq/ne/in/nin/contains/icontains`, wildcard, `AND/OR/NOT` | Self-hostable; `infer=False` skips the LLM but you still need an embedder; Docker + Postgres + Qdrant for the server | Heavy by default (LLM call per add to decide extract/update/delete) |
| **Letta (MemGPT)** | Apache-2.0 server, open-core | MCP *client*, not server; the popular Letta MCP server is community | **Yes, two ways.** Memory *blocks* are natively labeled (`{label, value, limit, …}`); archival passage search takes `tags[]` + **`tag_match_mode: "any"｜"all"`** — exactly our ALL semantics. But a `query` is still expected alongside | Self-hostable; **Postgres is the documented bottleneck** (≥80 conn pool) | Very heavy — a whole agent OS. Every memory write is an agent tool call |
| **Zep / Graphiti** | **Zep Community Edition deprecated Apr 2025**; only Graphiti (Apache-2.0, ~24k★) remains, explicitly "bring your own graph DB + your own retrieval tooling" | Yes, official + rich (`add_memory`, `search_nodes`, `search_memory_facts`, `get_episodes`, …) | **NO.** `query: str` is positional-required on every search tool. Only query-free call is `get_episodes(group_ids)` — a recency dump. "Labels" are LLM-assigned entity types, not your tags | Needs Neo4j/FalkorDB/Kuzu **and** an LLM with structured output | Heaviest. Multiple LLM calls per episode; cost complaints (~$1 per 4 files reported) |
| **Cognee** | Apache-2.0, but Postgres-as-graph-store is demo-only; production graph store is a licensed commercial product | Yes (`cognify`, `search`, `recall`, `add_rules`, …) | **Partial.** `node_name` filters to `node_set`s declared at `.add()` time — the right idea. But `query` is effectively mandatory and the default `SearchType.GRAPH_COMPLETION` runs an LLM to synthesize prose rather than return records | Best zero-key story of the graph systems (Ollama + SQLite + LanceDB + Kuzu) | Heavy — 3 stores to back up, docker-compose recommends 8 GB RAM floor, 30s query latencies reported |
| **Supermemory** | MIT repo, but production uses **proprietary tuned extraction models**; self-host stories conflict | Official hosted MCP, 4 thin tools (`addMemory`, `search`, `getProjects`, `whoAmI`) | **YES — richest filter language found.** `POST /v3/documents/list` takes nested AND/OR to 5 levels with `metadata｜numeric｜array_contains｜string_contains` conditions, `negate`, `ignoreCase`. No query needed. Caveat: `/v3/search` still requires `q` — filter-only is *listing*, not search. `containerTags` already deprecated → `containerTag` | Self-host claims no cloud key (installer wants an LLM key) | Medium, SaaS-shaped |
| **Memobase** | Apache-2.0, ~2.8k★, active | Yes, official in-repo | **Different shape, partially yes.** Maintains a structured `topic > sub_topic > content` user profile; `only_topics=[…]` is genuine query-free label filtering — but the labels are a *configured profile taxonomy*, not free-form per-memory tags. Modeling `pre-merge`/`p0` means bending the schema | Self-hostable; FastAPI + **Postgres + Redis** | Medium. 3 LLM calls per flush. Smallest community — bus-factor risk |
| **MemoryOS** | Apache-2.0 (research) | Yes | Tiered STM/MTM/LPM, heat-based promotion. Not label retrieval | Local possible | Research-grade |
| **A-MEM** | Research (Zettelkasten-style, auto-linking notes) | Community | Auto-generated **keywords/tags per note** + link evolution — the closest research system to tag-based | Local possible | Research-grade, not production |
| **Cipher / ByteRover** | **Elastic License 2.0** — not OSI open source; watch this | Yes (`brv mcp`) | Context trees, `/query`; semantic-first | Local by default, cloud optional | Medium |
| **claude-mem** | Apache-2.0 | Yes — `search`, `timeline`, `get_observations` | Filters by type/date/project; SQLite FTS5 + Chroma hybrid | Yes, local SQLite | Medium. **Its 3-layer progressive-disclosure tool design (search cheap → fetch details) is worth copying** |
| **OpenMemory (mem0)** | Apache-2.0 — **deprecated/sunset**, folded into the self-hosted mem0 server | Was an MCP server (`add_memories`, `search_memory`, `list_memories`, `delete_all_memories`) | Inherits mem0's filters | Local Docker (Postgres + Qdrant) | Medium-heavy. Don't build on it |
| **Redis Agent Memory Server** | Open source (Redis-led) | Yes — 7 tools | **Yes, genuinely**: `topics`, `entities`, `namespace`, `user_id`, `session_id`, `memory_type`, `event_date`, with `eq/ne/any/all/in/gte` operators over Redis TAG fields | Needs Redis Stack | Medium — **cleanest filter algebra to copy** (Supermemory's is richer but proprietary-flavoured and already churning) |
| **Basic Memory** | **AGPL-3.0** — disqualifying for a product | Yes, ~20 tools | Frontmatter tags + `[category]` observations; hybrid FTS+vector | Yes, markdown + SQLite | Medium. Philosophically the *opposite* of our principle — it's files-first, agent-edits-markdown |
| **LangMem** | MIT (LangChain) | No official MCP | Namespaces (tuples) + LangGraph `BaseStore`; `search` supports filter + query | Depends on store | Light-ish, but LangGraph-coupled |

Cross-cutting observations — these are what actually decide the build/buy call:

- **Only two systems in the entire survey let you retrieve by label with no query string**:
  mem0's `get_all(filters=…)` and Supermemory's `POST /v3/documents/list`. Every graph
  system (Graphiti, Cognee) makes `query` mandatory. That is the single clearest signal
  that this category is not built for our use case.
- **Benchmark claims here are not trustworthy.** Zep's teardown of mem0's LOCOMO SOTA
  claim alleges mem0 mis-implemented Zep (wrong user model, timestamps bypassing dedicated
  fields, sequential rather than parallel search), reporting Zep at 65.99% when the correct
  figure is 75.14%±0.17. mem0 counter-claims Zep is really 58.44%. Zep also points out
  that mem0's *own* table shows a plain full-context baseline (~73%) beating mem0 (~68%) —
  i.e. the benchmark doesn't stress memory at all. Letta has separately disputed mem0's
  numbers. Treat every vendor benchmark in this space as marketing.
- **Deprecation churn is severe.** In roughly 18 months: Zep Community Edition deprecated
  (Apr 2025), OpenMemory MCP deprecated, `mem0ai/mem0-mcp` archived (Mar 2026),
  Supermemory's `containerTags` deprecated, mem0 v1.0.0 shipped breaking changes including
  auth-on-by-default 401s. Adopting any of these is signing up for migrations on someone
  else's schedule, for a component that should be boring infrastructure.
- **Almost all require an LLM call at write time** — Graphiti (multiple), Cognee, Memobase
  (3 per flush), Letta (an agent tool call), Supermemory (extraction). Only mem0 with
  `infer=False` avoids it, and even then you need an embedder. We already know exactly what
  we want to write; paying an LLM call to decide is pure downside.
- **None treats labels as the *primary* retrieval axis.** Redis Agent Memory Server has the
  best filter algebra, and even there `topics` is auto-extracted metadata narrowing a
  semantic query, not a curated taxonomy.
- **None has an OSS curation UI worth adopting.** Letta's ADE is the only real one, and it's
  attached to a whole agent runtime. The one product that gets curation right — CodeRabbit
  — is closed source. Memobase's structured JSON profiles are the most diffable artifact in
  the survey and are worth a look purely as a data-shape reference.
- **What we'd actually be reimplementing** is `SELECT * FROM learnings WHERE tags @> …`
  over SQLite. That is the whole of it. Every system above hands you that only as a side
  effect of a full RAG stack you'd then have to operate.

---

## §2 — Labels vs. embeddings (the key design question)

**Opinionated answer: for this use case, labels win, and it isn't close. Ship labels only.**

The framing "labels vs. embeddings" hides the real variable: **who decides relevance, and
when.** Vector search defers the relevance decision to inference time and resolves it
statistically. Labels move the decision to *write* time (the author picks labels) and
*design* time (the template declares which labels a step needs). For a workflow engine
where the steps are known in advance, moving the decision earlier is strictly better —
it's the difference between a lookup and a guess.

**Where vector search genuinely wins** — and why none of it applies here:

- Unbounded, unstructured corpora where you can't anticipate the query. *We have ~11
  known workflow steps.*
- Vocabulary mismatch: user says "login problems," memory says "JWT expiry." *Our labels
  are a closed vocabulary we control on both sides.*
- Long-tail recall over thousands of items. *A healthy learnings store is 50–500 items.
  At that scale you can afford to be exhaustive within a label.*

**Known failure modes of vector-only memory** (all documented, all fatal for us):

1. **Non-determinism.** Same situation, slightly different phrasing, different top-k. A
   `p0` pre-merge safety rule that surfaces 80% of the time is worse than useless — it's
   a rule you can't reason about.
2. **Silent misses.** Top-k with a similarity floor returns *something*, always, and never
   tells you what it dropped. Our `unmatched_labels` field is the opposite design: the
   store tells you when it has nothing.
3. **Stacked contradictions.** Semantic search happily returns "prefer verbose" and
   "prefer terse" together; the model gets no signal about which is current. Fixed by
   explicit `supersedes`, not by better embeddings.
4. **Distractor sensitivity + context rot.** Chroma's context-rot study across 18 frontier
   models (GPT-4.1, Claude 4, Gemini 2.5, Qwen3) found accuracy degrading non-uniformly
   with input length — sometimes 30–50% — and found that semantically-similar-but-wrong
   distractors hurt disproportionately. Vector search's characteristic error is returning
   exactly those distractors.
5. **Memory poisoning.** Poisoned "successful experiences" injected into an experience
   pool get retrieved as trusted priors and persist across sessions until explicitly
   cleaned (see MemoryGraft, and the persistent-memory-poisoning literature). A
   human-curated, closed-vocabulary, provenance-tracked store with soft-delete is
   dramatically more auditable than a vector blob.

**Known failure modes of label-only** — be honest about these:

1. **Label drift** (`pre-merge` / `premerge` / `pre_merge`). → Closed vocabulary +
   `learnings_labels` + reject-unknown-by-default.
2. **Mislabeling at write time** = permanent invisibility. → `near_duplicates` on write,
   `suggested_labels` on read, and a curation UI where a human relabels.
3. **Cold-start / discovery**: an agent facing a novel situation doesn't know what to ask
   for. → This is the one real gap, and it's why `learnings_search` (FTS5, lexical) is on
   the v1.1 list. Note lexical, not vector: for a few-hundred-item store over a controlled
   vocabulary, BM25 gets you most of the recall for none of the infrastructure.
4. **Taxonomy ossification**: the vocabulary stops matching reality. → `open: true` facets
   plus periodic review in the UI.

**Is a hybrid worth doing?** Yes — eventually, and in a specific order: **labels as a hard
filter, lexical rank within.** That is: `WHERE label IN (...)` then BM25 over the matched
set. Never the reverse (semantic first, filter after), which is what most of the surveyed
systems do and which reintroduces every non-determinism problem. The industry is
converging on "metadata filtering is as important as semantic similarity" — AWS shipped
structured metadata filtering for AgentCore Memory, Elastic's guidance is to narrow with
structured filters *before* vector scoring. We should simply start at the end state:
filter first, and only add the ranking layer if needed.

**The honest counterargument:** if the learnings store grows to thousands of entries
spanning many repos and the workflow-step binding turns out to be too coarse (every
`step:code-review` call returns 60 learnings), you will want semantic ranking to pick the
top 10. Mitigate with the score/use_count ranking and the hard cap first. Embeddings are
a v2 optimization behind a proven problem, not a v1 requirement.

---

## §3 — MCP memory servers

**Official `@modelcontextprotocol/server-memory`** (MIT, knowledge-graph, JSONL storage):

- Tools: `create_entities`, `create_relations`, `add_observations`, `delete_entities`,
  `delete_observations`, `delete_relations`, `read_graph`, `search_nodes`, `open_nodes`.
- Model: entities (`name`, `entityType`, `observations[]`), relations (`from`, `to`,
  `relationType`), observations (strings).
- Storage: JSONL at `MEMORY_FILE_PATH`.
- **Good:** MIT, trivially forkable, zero dependencies, human-readable storage, no
  embeddings, works in both Claude Code and Codex today. `entityType` is a crude label.
- **Bad:** 9 tools (~9k tokens of schema) for a model we don't want. `search_nodes` is
  substring matching over names/types/observations — no tag semantics, no `all` vs `any`,
  no scoring. `read_graph` returns *everything*, which is the context bomb we're avoiding.
  The entity/relation ontology forces us to model learnings as graph nodes, which is
  ceremony with no payoff for a flat labeled list. It is also widely reported as being
  ignored by agents unless the system prompt aggressively instructs its use.
- **Verdict: not worth forking.** Read it for the stdio boilerplate (~200 lines) and move
  on. Our schema is simpler and our tool count is half.

**`doobidoo/mcp-memory-service`** — the most relevant community server:

- Has genuine tag support: `store_memory`, `retrieve_memory`, `search_by_tag`,
  `delete_by_tag`, `recall_memory` (natural-language time queries), and — per its docs —
  **ALL vs ANY tag matching across all backends**. Backends: SQLite-vec (default, local,
  ONNX embeddings, no credentials), ChromaDB, Cloudflare D1/Vectorize, Milvus, hybrid.
- **Good:** proves the exact design; tag-only retrieval is a first-class path; local-first
  default; active project.
- **Bad:** it's still fundamentally a semantic memory service with tags bolted on —
  embeddings are effectively mandatory (ONNX model download), the tool surface is large,
  and the data model has no `score`/`use_count`/`supersedes`/`confidence`, no curation
  story, and no workflow-step binding. Forking it means deleting more than we keep.
- **Verdict: strongest fork candidate, but still build.** Steal `search_by_tag`'s
  `match_all` semantics and its tag-storage approach.

**Others surveyed:** `shaneholloman/mcp-knowledge-graph` (fork of the official one, adds
timestamps/multi-project), `context-portal (ConPort)` (project-scoped knowledge graph,
heavier), `mcp-memory-libsql`, `T1nker-1220/memories-with-lessons-mcp-server` (notable —
explicitly adds a "lesson system" for error learning on top of the official server; small,
but confirms the demand and isn't well-maintained enough to depend on). None changes the
recommendation.

---

## §4 — How the coding agents handle this today, and what's wrong with it

**Claude Code — CLAUDE.md.** Hierarchical (enterprise → project → user → subdirectory),
`@path` imports, `#` shortcut to append a memory mid-session, `/memory` to edit. Plus, on
the API side, the **memory tool** (beta, `context-management-2025-06-27`): a client-side
`/memories` file directory with `view`/`create`/`str_replace`/`insert`/`delete`/`rename`
commands, paired with context editing (`clear_tool_uses_20250919`) that evicts old tool
results. Note that even Anthropic's own memory tool is **file-shaped** — it's a directory
of markdown the model edits. It solves persistence, not curation or conflict.

**The concrete case against file-based memory** (this is the section that justifies the
whole project):

- **It's never lazy-loaded.** CLAUDE.md is loaded before the code, before the task,
  before anything, and persists in context for the whole session. A 5k-token CLAUDE.md
  costs 5k tokens on turn 1 and on turn 200. Community guidance has converged on "keep it
  under ~200 lines" — which is another way of saying the mechanism doesn't scale.
- **Overhead dominates.** Measured breakdowns put ~75% of Claude Code input tokens in
  overhead (CLAUDE.md, tool schemas, hooks, skills) rather than the actual task. A whole
  cottage industry of CLAUDE.md token analyzers now exists.
- **Longer context is worse context.** Chroma's context-rot study: all 18 frontier models
  tested degrade with input length, non-uniformly, sometimes 30–50% before nominal limits.
  So a growing memory file doesn't just cost more — it makes the agent *worse at using
  the memory*.
- **Rules get ignored as the file grows.** This is the universal complaint across Claude
  Code, Cursor, and Windsurf. Cursor's own troubleshooting guidance is a litany of "your
  rule didn't apply" cases (glob didn't match; you set both `globs` and `description`;
  auto-attach only fires when the user mentions the file, not when the agent touches it).
- **Parallel agents conflict.** Nothing in the file-based model arbitrates two agents
  appending to the same markdown file in the same worktree. This is a real, mundane,
  daily failure for the workflow system we're building, and SQLite solves it outright.
- **No structure, therefore no UI, no curation, no metrics.** You cannot answer "which of
  these 90 rules has ever changed an outcome" from a markdown file.

**Codex — AGENTS.md.** A plain markdown convention (now the cross-vendor standard, adopted
by Amp, Windsurf, Cursor, Copilot, Jules). Same properties, same problems, plus: no `#`
append shortcut, no memory tool, no hooks worth speaking of. **Codex has no native memory
mechanism at all** — which strengthens the case for MCP, since MCP is the *only* thing
that gives us parity.

**Cursor — `.cursor/rules/*.mdc`.** Frontmatter: `description`, `globs`, `alwaysApply`.
This is the industry's most label-like design and is worth studying: it's conditional
loading keyed on a glob (a label over the file tree) or on an LLM reading a `description`
(a soft label). It's also the clearest evidence that the approach is fragile when the
trigger is heuristic — hence our decision to bind labels to *template steps*, which is
deterministic.

**Windsurf — memories + rules.** Auto-generated memories stored locally in
`~/.codeium/windsurf/memories/`, workspace-scoped. Hard limits: 6,000 chars global rules,
12,000 chars per workspace rule file. Windsurf's own docs recommend *not* relying on
auto-memories for anything you need reliably — write a rule instead. That's a vendor
admitting autosave-without-curation doesn't work, and it's precisely why our autosave
lands as `provisional`.

**Amp (Sourcegraph)** — AGENT.md, and a public push to make it the standard. Amp's stance
is minimalism plus subagents for context isolation rather than a rich memory layer.

**Devin (Cognition)** — the **Knowledge base** is the most sophisticated production
system found: every entry requires a **trigger description** in natural language, used as
a semantic cue for when to surface it ("When working on the payments-service repository
and writing database queries"). Org- and enterprise-scoped, with folders to enable/disable
sets. **The lesson:** Devin needed a per-entry trigger because it has no workflow model.
We have templates — our step *is* the trigger, for free and deterministically. Devin's
documented failure mode (vague triggers → knowledge surfaces at the wrong time or never)
is one we structurally avoid.

**GitHub Copilot** — `.github/copilot-instructions.md` plus `applyTo` frontmatter on
`*.instructions.md` files. Same glob-based conditional loading as Cursor.

---

## §5 — Prior art on "learnings"

**Reflexion** (Shinn et al. 2023) — verbal reinforcement learning: after a failure, the
agent writes a textual self-reflection into an episodic memory buffer, which is prepended
to the next attempt. *Lesson:* failure-triggered capture is high signal-to-noise. *Limit:*
the buffer is per-task and sliding-window — no cross-task transfer, no curation, no
labels. Reflexion is where the learnings idea starts, not where it ends.

**Generative Agents** (Park et al. 2023) — memory stream + reflection, retrieval scored as
a weighted sum of **recency** (exponential decay), **importance** (LLM-rated 1–10), and
**relevance** (embedding similarity). *Lesson:* relevance alone was never enough even in
the founding paper — importance and recency were needed from day one. Our `score`,
`use_count`, `last_used_at`, and `expires_at` are the same three signals, made explicit
and human-editable instead of LLM-guessed.

**Voyager** (Wang et al. 2023) — the **skill library**: verified, executable JavaScript
stored and retrieved by embedding of a natural-language description, composed for novel
tasks. *Lesson, and it's the big one:* **a learning that can be executed and verified beats
a learning that must be read and obeyed.** Where a learning can become a lint rule, a CI
check, a test, or a Claude Code hook, it should — that's principle #1 of the braindump
("push everything into tools and daemons"). The learnings store should be the fallback for
knowledge that *can't* be executable, and the curation UI should have a "promote to
automation" affordance. *Limit:* Voyager only stores *successes*; it has no mechanism for
"don't do X."

**ExpeL** (Zhao et al., AAAI 2024) — the closest academic match. Collects success and
failure trajectories, then distils an **insight pool** of natural-language insights,
maintained by an LLM with four operations: **ADD** (new insight, initial importance count
of 2), **EDIT**, **UPVOTE**, **DOWNVOTE**. At eval time it retrieves both similar
trajectories and the insight pool. *Lesson:* adopt the operation set and the importance
counter verbatim — this is `learnings_update`. *Limit:* the pool is global and unlabeled;
ours is labeled and step-scoped, which is strictly better for a workflow engine.

**Agent Workflow Memory** (Wang et al. 2024) — induces reusable *workflows* from past
experience and reuses them. *Lesson:* the unit of learning is sometimes a whole procedure,
not a fact. Maps to our **templates**: a sufficiently reinforced cluster of learnings on
one step is a signal that the template itself should change.

**Production systems:**

- **CodeRabbit Learnings** — the state of the art in shipping products, and the model to
  copy. Natural-language learnings created from reviewers replying to review comments;
  stored with PR number, filename, creating user, timestamp, and usage stats; credential
  redaction before persistence; scope config (`local` / `global` / `auto`); loaded on
  every review according to scope; a dashboard at `app.coderabbit.ai/learnings` with
  sortable/filterable tables, semantic search, inline edit and delete; CSV export/import;
  optional approval workflow delaying application of new learnings up to 30 days. Every
  one of those is a design decision we should copy. Note that even CodeRabbit's *retrieval*
  is scope-based (load all in-scope learnings), not semantic — semantic search is for the
  *human* browsing the dashboard. That's a strong independent validation of labels-over-
  embeddings.
- **Devin Knowledge** — see §4.
- **Cursor Memories / Windsurf Memories** — auto-generated, uncurated, unreliable by
  vendor admission.

**On rot** — the failure modes are well documented and all three apply to us:
**staleness** (a fact silently stops being true and nothing ever contradicts it),
**contradiction** (two opposing learnings both retrieved, no recency signal), and
**poisoning** (adversarial or simply wrong "experience" retrieved as trusted prior,
persisting until manually cleaned). The literature's mitigations — supersession-on-write,
temporal decay of trust scores, threshold-based exclusion, explicit eviction — are exactly
`supersedes`, `score`, auto-retire at score ≤ 0, and `expires_at`. Build them in v1; they
are cheap now and impossible to retrofit once the store is full.

---

## §6 — Todo store

**Claude Code's `TodoWrite`**: `todos: [{ content, activeForm, status }]` where `status ∈
{pending, in_progress, completed}`, `content` is imperative ("Run tests"), `activeForm` is
present continuous ("Running tests"). Guidance: use for 3+ step tasks; exactly one
`in_progress` at a time; mark complete only when fully done; add follow-ups as discovered.
Returns a stats summary (total/pending/in_progress/completed) rather than echoing the
list.

**Codex's `update_plan`**: steps with status `pending | in_progress | completed`, with
`append` and `update`-by-index operations; guidance says update after each sub-task and
never end with `in_progress`/`pending` items.

**Why tool-mediated beats a file** — and it's not primarily about tokens:

1. **The response is a summary, not the document.** TodoWrite returns counts. Re-reading
   and re-writing a TODO.md costs the full document twice per mutation.
2. **Atomic partial mutation.** "Mark step 4 in_progress" is one small call. In a file
   it's read-all + edit + write-all, and two parallel agents doing that clobber each other.
3. **It's renderable.** The host draws a checklist UI. A markdown file is just more text
   in the transcript. This is exactly our principle #2 — and for our workflow status
   board, structured todo state is the *input*.
4. **It's observable.** The controller can read todo state without reading transcripts —
   precisely the low-context controller the braindump wants.
5. **Validity is enforceable.** "Exactly one in_progress" is a server-side invariant, not
   a prompt instruction the model may ignore.

**Design ours to mirror TodoWrite closely** — three tools, and deliberately *not*
general-purpose:

- `todo_list({ run_id?, status? })` → items with `id`, `content`, `activeForm`, `status`,
  `owner` (`agent:<id>` | `human`), `blocked_on`, `step`.
- `todo_set({ id, status, note? })` — single-item mutation, server enforces one
  `in_progress` per owner.
- `todo_add({ items: [...], run_id, after? })` — batch append.

Two additions over TodoWrite that our system specifically needs: **`owner`** (so a
sub-controller's todos and a leaf agent's todos are distinguishable on the status board)
and **`status: "blocked"` + `blocked_on`** (human-owned steps like "manual test" block
until a human resolves them — that's a first-class state in the braindump's template, and
TodoWrite has no way to express it).

**Forkable todo MCP servers:** `cjo4m06/mcp-shrimp-task-manager` (MIT, JSON storage,
chain-of-thought planning with dependency tracking), `flesler/mcp-tasks` (multi-format
markdown/JSON/YAML), `bsmi021/mcp-task-manager-server` (SQLite), `claude-task-master`.
**None is worth forking** — todo state must be the same store the controller and status
board read, so it has to be ours. They're each ~500 lines; read Shrimp for its dependency
model and write our own.

---

## §7 — Claude Code / Codex parity notes

This is where most of the practical risk lives.

- **Transport: use stdio.** Both support it, everywhere, with no auth story. Codex also
  supports Streamable HTTP (`url` + `bearer_token_env_var`); Claude Code supports SSE/HTTP.
  A single stdio binary is the lowest common denominator and the least to go wrong.
- **Configuration differs and can't be unified.** Claude Code: `.mcp.json` in the project
  (or `claude mcp add`). Codex: TOML at `~/.codex/config.toml` or `.codex/config.toml`
  (trusted projects only), under `[mcp_servers.<name>]` with `command`/`args`/`env`, plus
  a `codex mcp add` subcommand. **Ship an installer** (`agentflow init`) that writes both
  — do not make users hand-edit two formats. This is a five-line generator and it removes
  the single most common onboarding failure.
- **Tools only. No resources, no prompts.** MCP prompts are *not consumed by Codex CLI*.
  Resources were historically ignored or caused outright failures in Codex, and there are
  reported bugs where Codex probes `resources/list` to decide server availability and
  chokes on servers that don't implement it. Recent Codex releases (v0.119/v0.120,
  Apr 2026) added resource reads, output schemas and elicitations, but **do not depend on
  any of it** — implement `resources/list` returning `[]` defensively, and put 100% of
  functionality behind tools.
- **Hooks are Claude-only.** Claude Code has SessionStart/UserPromptSubmit/PostToolUse/
  Stop/SessionEnd/PreCompact. Codex's tool events don't cover MCP calls. Therefore
  **autosave must live in the controller, not in agent hooks**, or it will only work for
  half our users. Use Claude hooks as an *optimization* where available, never as the
  mechanism.
- **Tool descriptions are your only prompt surface on Codex.** No CLAUDE.md-equivalent you
  control, no skills, no hooks. Every behavioral instruction ("call `learnings_get` before
  starting a review step", "prefer `learnings_labels` over inventing a label") must be
  encoded in the tool descriptions themselves — and kept short, because they're loaded
  every turn on both platforms.
- **Budget the schema.** 4 learnings tools + 3 todo tools ≈ 7 × ~1k = ~7k tokens on every
  agent. That's already significant. Keep descriptions terse, avoid deep nested objects
  (nesting is a documented token multiplier), and consider gating the todo tools to
  controller agents only.
- **Naming:** namespace tools consistently (`learnings_*`, `todo_*`). Claude Code prefixes
  MCP tools as `mcp__<server>__<tool>`; keep names short so the composed name stays
  readable in transcripts and hook matchers.

---

## Build plan (scope check)

1. SQLite schema + JSON row shape + secret redaction. (~150 LOC)
2. stdio MCP server, 4 learnings tools. (~250 LOC, plus boilerplate from the official
   server)
3. `agentflow init` writing `.mcp.json` and `~/.codex/config.toml`. (~50 LOC)
4. Template-step → label binding in the workflow runtime; auto-inject `learnings_get`
   results into step prompts.
5. Todo tools against the same DB (the status board reads it directly).
6. Curation UI: a table over the rows. `score`, `use_count`, `confidence`, promote/edit/
   retire. Provisional-learnings inbox.
7. Autosave: controller-side extraction at step boundaries → `confidence: provisional`.

Items 1–3 are the MVP and are genuinely a couple of days. Item 4 is the differentiator.
Item 6 is what stops it rotting in month three.

---

## Sources

Memory systems & benchmarks
- https://github.com/mem0ai/mem0 · https://docs.mem0.ai/open-source/features/metadata-filtering
- https://docs.mem0.ai/platform/platform-vs-oss · https://docs.mem0.ai/migration/breaking-changes
- https://github.com/mem0ai/mem0-mcp (archived Mar 2026)
- https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/
- https://github.com/getzep/zep-papers/issues/5 (mem0 rebuttal)
- https://blog.getzep.com/announcing-a-new-direction-for-zeps-open-source-strategy/
- https://github.com/getzep/graphiti · https://help.getzep.com/graphiti/getting-started/mcp-server
- https://docs.letta.com/api/resources/agents/subresources/passages/methods/search
- https://docs.letta.com/guides/agents/memory-blocks/
- https://github.com/topoteretes/cognee · https://docs.cognee.ai/api-reference/search/search
- https://docs.cognee.ai/guides/local-setup
- https://github.com/supermemoryai/supermemory · https://supermemory.ai/docs/search/filtering
- https://github.com/memodb-io/memobase · https://docs.memobase.io/api-reference/profiles/profile
- https://mem0.ai/research
- https://mem0.ai/blog/memory-eviction-and-forgetting-in-ai-agents
- https://vectorize.io/articles/mem0-vs-letta
- https://thegenios.com/blog/open-source-memory-layers-2026/
- https://redis.github.io/agent-memory-server/mcp/
- https://redis.github.io/agent-memory-server/long-term-memory/
- https://github.com/basicmachines-co/basic-memory
- https://github.com/thedotmack/claude-mem
- https://github.com/campfirein/cipher
- https://langchain-ai.github.io/langmem/
- https://deepwiki.com/doobidoo/mcp-memory-service
- https://github.com/modelcontextprotocol/servers/tree/main/src/memory

Labels vs. embeddings
- https://www.mindstudio.ai/blog/agent-memory-problem-vector-search-not-enough
- https://aws.amazon.com/blogs/machine-learning/structured-memory-filtering-with-metadata-in-agentcore-memory/
- https://www.elastic.co/search-labs/blog/ai-agent-memory-management-elasticsearch
- https://www.trychroma.com/research/context-rot
- https://hamel.dev/notes/llm/rag/p6-context_rot.html
- https://arxiv.org/html/2601.05504v2 (memory poisoning attack/defense)
- https://arxiv.org/pdf/2512.16962 (MemoryGraft)
- https://christian-schneider.net/blog/persistent-memory-poisoning-in-ai-agents/

Coding agents & file-based memory
- https://docs.claude.com/en/docs/agents-and-tools/tool-use/memory-tool
- https://platform.claude.com/cookbook/tool-use-memory-cookbook
- https://code.claude.com/docs/en/costs
- https://acdigest.substack.com/p/most-of-your-claude-code-tokens-are
- https://ccmd.dev/
- https://docs.windsurf.com/windsurf/cascade/memories
- https://forum.cursor.com/t/cursor-rules-mdc-clarification/104879
- https://sdrmike.medium.com/cursor-rules-why-your-ai-agent-is-ignoring-you-and-how-to-fix-it-5b4d2ac0b1b0
- https://docs.devin.ai/product-guides/knowledge
- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

Learnings / reflection prior art
- https://docs.coderabbit.ai/knowledge-base/learnings
- https://andrewzh112.github.io/expel/ and https://arxiv.org/html/2308.10144v3
- https://arxiv.org/html/2603.07670v1 (memory for autonomous LLM agents survey)
- https://arxiv.org/html/2602.20867v1 (SoK: Agentic Skills)

Todos & MCP practicalities
- https://github.com/Piebald-AI/claude-code-system-prompts/blob/main/system-prompts/tool-description-todowrite.md
- https://code.claude.com/docs/en/agent-sdk/todo-tracking
- https://github.com/openai/codex/pull/24794 (built-in tool schema docs)
- https://github.com/cjo4m06/mcp-shrimp-task-manager
- https://developers.openai.com/codex/mcp
- https://codex.danielvaughan.com/2026/04/11/codex-cli-mcp-maturation-resource-reads-outputschema/
- https://github.com/openai/codex/issues/8565 (Codex resources/list probing bug)
- https://www.anthropic.com/engineering/advanced-tool-use
- https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2808 (tool schema token overhead)
