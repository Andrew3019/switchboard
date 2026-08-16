# Instruction layering across claude and codex — the structural model

Round 2. No code changed. This is the model to accept or amend; the evidence behind every
claim is in `notes/codex-layering-probe.md` (live trials against `codex-cli 0.147.0` and
`claude 2.1.233`) and `notes/codex-prior-art.md` (what other orchestrators do).

The scenario this must not regress: a user runs Claude Code on their project with a repo
`CLAUDE.md`, adopts sb, then adds codex agents through sb. Their `CLAUDE.md` must still be
in force for those codex agents, and sb's protocol must still outrank it.

## The governing principle

**sb synthesizes only its own prompt. Everything the user already has passes through the
provider's own native discovery, untouched and unduplicated.** sb inlines a user's file
only where the provider cannot be made to read it natively — which turns out to be exactly
one case (§4).

This is what keeps the two providers honest against each other: sb is not maintaining a
port of the user's rules, so there is nothing to drift.

## The layers, in force order

### codex

| # | Layer | How it gets there | Authority |
|---|---|---|---|
| 1 | sb protocol + role + presets | `CODEX_HOME/AGENTS.md`, written per agent by sb | **wins — but only because it says so**, see §2 |
| 2 | repo `AGENTS.md`, else repo `CLAUDE.md` | codex's own project-doc lookup, with `project_doc_fallback_filenames = ["CLAUDE.md"]` set in `CODEX_HOME/config.toml` | beats layer 3; loses to layer 1 |
| 3 | user's `~/.codex/AGENTS.md` | inlined by sb into `CODEX_HOME/AGENTS.md`, below the protocol, explicitly demoted | lowest |

### claude

| # | Layer | How it gets there | Authority |
|---|---|---|---|
| 1 | sb protocol + role + presets | `--append-system-prompt-file` | **wins by construction** — system-level vs context-level |
| 2 | repo `CLAUDE.md` (and nested ones up the tree) | Claude Code's native discovery; sb does not touch it | beats layer 3 |
| 3 | user's `~/.claude/CLAUDE.md` | Claude Code's native discovery | lowest |

The two tables are deliberately the same shape. The only structural difference is that
codex needs sb to do work at layers 2 and 3 that Claude Code does for itself.

## §1 — Repo `CLAUDE.md` reaches codex natively, via the fallback list

`project_doc_fallback_filenames = ["CLAUDE.md"]` in the private `CODEX_HOME/config.toml`
makes codex read a repo `CLAUDE.md` as its project doc when no `AGENTS.md` is present
(verified). This is the recommended mechanism over sb reading `CLAUDE.md` and inlining its
text, for four reasons:

- **No duplication.** If the repo has both files, codex reads `AGENTS.md` and the fallback
  goes inert — the same precedence a human would expect, for free. An inlining approach has
  to reimplement that decision and gets to be wrong about it.
- **Not a snapshot.** The file is read per turn from disk, so edits during a long session
  take effect. An inlined copy is frozen at spawn.
- **Correct nesting semantics.** codex resolves the project doc by walking up from cwd,
  nearest-wins, single doc (verified — nested docs replace, they do not merge). The
  fallback list inherits that behaviour exactly; inlining a root-level file would silently
  override a nearer one.
- **Zero repo footprint.** The config is private to the agent. A human's own codex session,
  running the default `CODEX_HOME`, never sees this key (verified against the real
  `~/.codex/config.toml`).

The one cost: the project-doc slot is capped at `project_doc_max_bytes`, default 32768,
and truncation is **silent and mid-line**. A 60KB `CLAUDE.md` lost everything past 32KB
with no warning to model or operator. So sb must also write `project_doc_max_bytes` at a
raised value into the same private config (verified to fix it at 100000). Treat that as
part of the mechanism, not an optional tuning knob.

Rejected alternative: writing an `AGENTS.md` into the repo (or symlinking it to
`CLAUDE.md`). Anthropic blesses that pattern for humans, but for sb it fails the leakage
test — the file would be picked up by the human's own codex sessions and by every other
agent sharing the worktree, and it mutates a tracked file sb does not own. `CODEX_HOME`
exists precisely so we never do this.

## §2 — sb's prompt must assert its own authority, and this changes the prompt corpus

The sharpest finding of the round. codex injects **both** the global doc and the project
doc as *user*-role messages, concatenated global-then-project. With no authority language
in either, the model follows the **later** one — the repo doc. Verified 7/7 across two
unrelated topics: a plain sb protocol **loses** to a plain repo `AGENTS.md`/`CLAUDE.md` on
direct conflict.

Adding explicit override-authority wording to the `CODEX_HOME` doc flips this reliably —
it won even against a repo doc making the symmetric claim.

Claude Code needs none of this: `--append-system-prompt-file` is a true system-prompt
append and beat repo `CLAUDE.md` with no special wording (verified 2/2).

**Decision: the authority preamble goes into the shared prompt corpus, for both
providers.** Not a codex-only variant. It is required for codex, accurate for Claude
(sb's protocol already outranks repo rules there in practice), and keeping it in one place
is what preserves the single-corpus property Andrew asked for. The corpus stays one file
set; only delivery differs — flattened into a system-prompt file for Claude, written
unflattened as markdown for codex.

This is a real change to what the protocol *says*, not just how it ships, so it wants
review on its own terms. The wording needs to assert precedence over conflicting
project-level instructions without inviting an agent to ignore a repo's legitimate rules —
the intent is "sb's protocol governs how you operate; the repo governs the work."

## §3 — Where sb must be deliberate about cwd

codex's project-doc lookup is nearest-wins from cwd, and a nested doc *replaces* the root
one rather than merging (verified). If sb ever spawns a codex agent with cwd inside a
subdirectory, a `sub/AGENTS.md` becomes the entire project-doc layer and the repo-root
rules vanish. sb spawns at the worktree root today, so this is latent — but it should be
an explicit invariant, not an accident.

## §4 — The one genuine regression, and the fix

Pointing `CODEX_HOME` at a private directory silently drops the user's own
`~/.codex/AGENTS.md`, because that file *is* the global-doc slot under the default
`CODEX_HOME`. There is no pass-through: a codex process has exactly one home.

So this is the single case where sb must inline. sb reads `~/.codex/AGENTS.md` at spawn and
appends it to the per-agent `AGENTS.md` under a marked heading, explicitly demoted — it
carries neither the protocol's asserted authority nor precedence over repo rules.

Currently inert on this machine (the file is 0 bytes), but it bites the moment the user or
any tool populates it.

**Not doing the mirror-image thing:** sb will *not* feed `~/.claude/CLAUDE.md` to codex
agents. Personal globals are per-tool by the user's own choice, and importing one vendor's
personal config into the other is a surprise, not a convenience. Repo-level rules are
shared project truth and do cross over; user-level ones do not. Flagging this as the most
amendable call in the document.

## §5 — Failure modes, and whether this model closes them

| Failure mode | Closed? |
|---|---|
| sb protocol loses to a conflicting repo doc (codex) | Only by the §2 authority preamble. Without it, **open** |
| sb protocol loses to a conflicting repo `CLAUDE.md` (claude) | Closed by construction |
| Repo `CLAUDE.md` invisible to codex agents | Closed by the fallback list (§1) |
| Large `CLAUDE.md` silently truncated at 32KB | Closed only if sb also raises `project_doc_max_bytes` (§1) |
| Same rules delivered twice (inlined *and* natively read) | Closed — sb inlines nothing that codex reads natively |
| sb-written `AGENTS.md` leaking into human sessions / other agents in the worktree | Closed — sb never writes into the repo |
| Private `CODEX_HOME` config bleeding into the real `~/.codex/config.toml` | Closed (verified) |
| User's `~/.codex/AGENTS.md` silently dropped | Closed by the §4 inline |
| Nested doc shadowing the root doc sb expects | Closed by the cwd invariant (§3) |

## §6 — Hard requirements carried in from prior art

The space is thin — most multi-CLI orchestrators treat each provider as an opaque PTY —
but three findings are load-bearing:

- **A re-block cap in sb's Stop gate is mandatory, not defensive.** `openai/codex` #37937
  is an open, unresolved bug: a repeatedly-blocking Stop hook traps codex in an unbounded
  loop with no escape, and codex does not distinguish "hook infrastructure broke" from
  "policy denial". Our own probe hit the same shape (11 re-blocks on one turn). codex's
  `stop_hook_active` flag is not proven to prevent it. Cap it ourselves.
- **The Stop hook may not fire when a turn is interrupted with Esc** (`openai/codex`
  #22858). sb uses Esc for `--interrupt`. The done-gate silently not firing on that path
  would read as a hang.
- **Don't build on `-c developer_instructions=`.** AWS's `cli-agent-orchestrator` uses it
  and its docs frame it as a developer-role channel; per OpenAI's own discussion #7296 it
  is just text appended after `AGENTS.md` — no more authority than what we already have.
  `experimental_instructions_file` replaces the entire base system prompt and is labelled
  experimental by OpenAI. Neither is a shortcut past §2.

Two smaller ones worth keeping: `codex exec` blocks forever on stdin unless given
`< /dev/null` (hit repeatedly while probing), and `--output-last-message <file>` is a
cheaper source of "the final answer" than parsing rollout JSONL — relevant when the
transcript reader gets built.

## What this changes about the round-1 plan

Additions to "what has to be built": the authority preamble in the prompt corpus (§2);
`project_doc_fallback_filenames` + raised `project_doc_max_bytes` in the generated
`CODEX_HOME/config.toml` (§1); the `~/.codex/AGENTS.md` inline (§4); a re-block cap in the
Stop gate (§6). Nothing in round 1 is retracted.
