# Instruction layering across claude and codex — the structural model

Current as of round 3; supersedes the round-2 version of this file wholesale. Every claim
here is backed by live trials against `codex-cli 0.147.0` and `claude 2.1.233`, recorded in
`notes/codex-layering-probe.md`, `notes/codex-authority-wording.md`,
`notes/codex-repo-doc-mechanism.md`, `notes/codex-user-globals.md`, with prior art in
`notes/codex-prior-art.md`. No switchboard code has been changed.

The scenario this must not regress: a user runs Claude Code on their project with a repo
`CLAUDE.md`, adopts sb, then adds codex agents through sb. Their `CLAUDE.md` must still be
in force for those codex agents, and sb's protocol must still outrank it — but only on how
the agent operates, never on the work itself.

## The governing principle

**sb synthesizes only its own prompt. Everything the user already has passes through the
provider's own native discovery, untouched and unduplicated.** sb inlines a user's file
only where the provider cannot be made to read it natively — which is exactly one case
(§4).

This is what keeps the two providers honest against each other: sb is not maintaining a
port of the user's rules, so there is nothing to drift. It is also, empirically, the
safer choice — §3 shows that every place sb reimplements a lookup codex already does, sb
gets it wrong in a measurable way.

## The layers, in force order

### codex

| # | Layer | How it gets there | Authority |
|---|---|---|---|
| 1 | sb protocol + role + presets | `CODEX_HOME/AGENTS.md`, written per agent by sb | wins **on operating procedure only** — and only because it says so (§2) |
| 2 | repo `AGENTS.md`, else repo `CLAUDE.md` | codex's own project-doc lookup, via `project_doc_fallback_filenames = ["CLAUDE.md"]` in `CODEX_HOME/config.toml` | governs the work; beats layer 3 |
| 3 | user's `~/.codex/AGENTS.md`, else `~/.claude/CLAUDE.md` | inlined by sb into `CODEX_HOME/AGENTS.md`, with a demotion disclaimer (§4) | lowest |

### claude

| # | Layer | How it gets there | Authority |
|---|---|---|---|
| 1 | sb protocol + role + presets | `--append-system-prompt-file` | wins by construction — system-level vs context-level |
| 2 | repo `CLAUDE.md` (and nested ones up the tree) | Claude Code's native discovery; sb does not touch it | governs the work; beats layer 3 |
| 3 | user's `~/.claude/CLAUDE.md` | Claude Code's native discovery | lowest |

The two tables are deliberately the same shape. The only structural difference is that
codex needs sb to do work at layers 2 and 3 that Claude Code does for itself.

## §1 — Repo `CLAUDE.md` reaches codex natively, via the fallback list

`project_doc_fallback_filenames = ["CLAUDE.md"]` in the private `CODEX_HOME/config.toml`
makes codex read a repo `CLAUDE.md` as its project doc when no `AGENTS.md` is present, and
`project_doc_max_bytes` raised alongside it stops the silent 32KB truncation. Both keys
work from the private config; verified with a 424KB `CLAUDE.md` arriving whole.

This was settled against the alternative — sb reading `CLAUDE.md` and inlining its text
into the global slot — on evidence, in `notes/codex-repo-doc-mechanism.md`. Two round-2
arguments did **not** survive that scrutiny and are retracted here:

- *"Inlining is strictly safer against truncation."* False once the cap is raised. Both
  mechanisms hit the identical real ceiling — the model's context window — with the same
  loud error (`Codex ran out of room in the model's context window`) at ~9.5MB. There is no
  mechanism-specific ceiling above the configured cap.
- *"The fallback list re-reads from disk each turn, so edits take effect."* Not
  demonstrated. Under `codex exec resume`, the project doc is captured once at the start of
  the transcript and a mid-session edit did **not** reach the resumed turn. The interactive
  TUI path sb will actually use is untested by anyone so far. Treat both mechanisms as
  effectively spawn-time snapshots until someone tests the real path.

What decided it instead is that inlining forces sb to reimplement two of codex's own
lookups, and a plausible first-pass implementation gets both wrong — live-tested:

- **`AGENTS.md`-wins.** A naive inline that doesn't check for a repo `AGENTS.md` first
  makes a stale `CLAUDE.md` beat the human's real, current `AGENTS.md` — *once sb adds the
  authority preamble it has already committed to adding* (§2). Without the preamble the bug
  hides; with it, it bites.
- **Nearest-doc-from-cwd.** With cwd in a subdirectory that has its own `AGENTS.md`, an
  inlined root `CLAUDE.md` won 1 run in 5 — a coin flip, not a clean failure. Latent today
  because sb spawns at the worktree root, but one line of spawn code away from live.

The fallback list gets both for free, inside codex, deterministically. It is also less sb
code: two config keys, no file reading, no precedence logic, no cwd resolution, and nothing
to recompose on restore.

**Main risk, named:** this depends on codex continuing to honour those two config keys. If
a future release drops or renames them, the repo doc silently stops reaching the agent —
the same silent shape as a missing file. Worth a version pin or a startup smoke-check when
this ships.

Rejected outright: writing an `AGENTS.md` into the repo, or symlinking it to `CLAUDE.md`.
Anthropic blesses that pattern for humans, but for sb it fails the leakage test — the file
would be read by the human's own codex sessions and by every other agent sharing the
worktree, and it mutates a tracked file sb does not own. `CODEX_HOME` exists precisely so
we never do this.

## §2 — sb's prompt asserts narrow authority, and this changes the prompt corpus

codex injects **both** the global doc and the project doc as *user*-role messages,
concatenated global-then-project. With no authority language in either, the model follows
the **later** one — the repo doc. A plain sb protocol loses to a plain repo doc: verified
7/7 in round 2 on factual conflicts, and again 5/5 in round 3 on an operational conflict
("when you finish, never call `sb done`, just stop silently" — the repo doc won every
time). Claude Code needs none of this; `--append-system-prompt-file` wins by construction.

The wording is narrow by ruling: **sb's protocol governs how you operate as an agent; the
repo governs the work.** Repo rules about the code — style, lint, do-not-touch paths,
commit conventions — stay fully binding.

**Proposed text for the shared corpus:**

> This document governs how you operate as an agent — reporting, turn discipline,
> delegation, and the done gate. A project-level document governs the work itself, and its
> rules about the code — style, lint, do-not-touch paths, commit conventions — remain fully
> binding on you. Where a project-level document conflicts with this one on how you
> operate, not on the work, this document wins, always, without exception.

40 trials (2 conditions × 4 wordings × 5 runs) say this costs nothing against the blunt
absolute version it replaces: narrow ties blunt 5/5 on the operational collision, and both
tie the no-preamble control 5/5 on repo code-rule obedience. The specific fear — that blunt
wording would make an agent discard a legitimate repo code rule — did not reproduce, so
narrow wording is chosen on scope and register, not because blunt was measurably harmful.

The preamble goes into the **shared** corpus, for both providers: required for codex,
accurate for Claude, and keeping it in one place is what preserves the single-corpus
property. It changes what the protocol *says*, so it wants review on its own terms.

**Untested edge:** every trial used rules that were unambiguously operational or
unambiguously about the code. A rule sitting on the boundary — "never commit without
running the linter first" — was not probed, and is where narrow and blunt wording could
plausibly diverge.

## §3 — Where sb must be deliberate about cwd

codex's project-doc lookup is nearest-wins from cwd, and a nested doc *replaces* the root
one rather than merging. If sb ever spawns a codex agent with cwd inside a subdirectory, a
`sub/AGENTS.md` becomes the entire project-doc layer and the repo-root rules vanish. sb
spawns at the worktree root today, so this is latent — but it should be an explicit
invariant, not an accident.

## §4 — Personal globals: a fallback chain, one file, always demoted

Pointing `CODEX_HOME` at a private directory silently drops the user's own
`~/.codex/AGENTS.md`, because that file *is* the global-doc slot under the default
`CODEX_HOME`. A codex process has exactly one home, so there is no pass-through. This is
the single case where sb must inline.

**The rule:**

1. Read `~/.codex/AGENTS.md`. Trim; if non-empty, inline it.
2. Else read `~/.claude/CLAUDE.md`. Trim; if non-empty, inline it, with the extra
   cross-tool framing clause below.
3. Else inline nothing — no personal-globals section at all.

Only one is ever inlined, never both. Empty and whitespace-only count as absent, which is
not an sb invention: codex itself skips an empty global doc entirely rather than injecting
an empty `<INSTRUCTIONS>` block (verified three ways). Both real files are 0 bytes on this
machine today, so the chain currently terminates at step 3.

**The disclaimer sentence is load-bearing and is not decoration.** Verified 12/12: with an
explicit "does not carry the authority above, project-level docs override it" line, the
repo rule correctly beats the inlined personal rule. *Without* that line — same content,
same heading, merely sitting below the protocol — the personal rule beat the repo rule 4/4,
backwards from intended. Proximity to an authority-claiming section is enough for a
demoted section to inherit that authority. Whether the heading names the source file made
no measurable difference (8/8 either way); name it anyway, so a human skimming the composed
prompt can see where a line came from.

Section sb writes, for the codex case:

```
## Personal instructions imported from ~/.codex/AGENTS.md

The following was found in the user's personal ~/.codex/AGENTS.md and is included for
awareness only. It does not carry the authority above, and any project-level document
(AGENTS.md/CLAUDE.md in the repo) overrides it on conflict.

<verbatim content>
```

For the `~/.claude/CLAUDE.md` fallback, the same disclaimer plus a cross-tool clause, since
a Claude memory file may reference slash commands, subagents, hooks and tool names that do
not exist in codex:

```
## Personal instructions imported from ~/.claude/CLAUDE.md (no ~/.codex/AGENTS.md found)

The following is the user's personal Claude Code memory file, included here because no
personal codex AGENTS.md was found. It was written for a different coding agent and may
reference tools, commands, or subagents that don't exist in this environment — apply what
is substantively about coding style or workflow, and disregard anything that names a
Claude Code-specific mechanism you don't have. It does not carry the authority above, and
any project-level document (AGENTS.md/CLAUDE.md in the repo) overrides it on conflict.

<verbatim content>
```

The cross-tool clause is reasoned, not trial-verified — no probe used realistic
Claude-idiom fixture content to confirm the model actually filters inapplicable mechanics
rather than attempting them.

Note that sb only reads these files off disk, so the import does not depend on how Claude
Code itself ranks its own memory file. That is just as well: it remains **assumed, not
observed**, that `~/.claude/CLAUDE.md` is read and merged the way the docs describe.
Verifying it needs `CLAUDE_CONFIG_DIR` (confirmed as the right env var — `HOME` is not) plus
a fresh `claude login` in a disposable directory, since relocating the config root strands
the real credentials.

## §5 — Failure modes, and whether this model closes them

| Failure mode | Closed? |
|---|---|
| sb protocol loses an operational collision with a repo doc (codex) | Closed by the §2 preamble; **open** without it (5/5 loss) |
| sb protocol overrides legitimate repo code rules | Closed — repo rules kept 5/5 under the narrow wording |
| sb protocol loses to a conflicting repo `CLAUDE.md` (claude) | Closed by construction |
| Repo `CLAUDE.md` invisible to codex agents | Closed by the fallback list (§1) |
| Large `CLAUDE.md` silently truncated at 32KB | Closed only if sb also raises `project_doc_max_bytes` (§1) |
| Stale `CLAUDE.md` outranking the repo's real `AGENTS.md` | Closed by not inlining — codex decides (§1) |
| Nested doc shadowed by a stale root copy | Closed by not inlining; coin-flip failure if we did (§1) |
| Same rules delivered twice | Closed — sb inlines nothing codex reads natively |
| sb-written `AGENTS.md` leaking into human sessions / other agents in the worktree | Closed — sb never writes into the repo |
| Private `CODEX_HOME` config bleeding into the real `~/.codex/config.toml` | Closed (verified) |
| User's personal globals silently dropped | Closed by the §4 chain |
| Inlined personal globals outranking repo rules | Closed **only** by the disclaimer sentence; open without it (4/4 loss) |
| Nested doc shadowing the root doc sb expects | Closed by the cwd invariant (§3) |
| codex drops the `project_doc_*` config keys in a future release | **Open** — needs a version pin or startup smoke-check (§1) |

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
`< /dev/null`, and `--output-last-message <file>` is a cheaper source of "the final answer"
than parsing rollout JSONL — relevant when the transcript reader gets built.

## §7 — What this adds to the build list

On top of round 1's list (`notes/codex-support-findings.md`):

- the narrow authority preamble in the shared prompt corpus (§2);
- `project_doc_fallback_filenames = ["CLAUDE.md"]` and a raised `project_doc_max_bytes` in
  the generated `CODEX_HOME/config.toml` (§1);
- the personal-globals fallback chain, with its disclaimer sentence, composed into the
  per-agent `AGENTS.md` (§4);
- a re-block cap in the Stop gate (§6);
- an explicit worktree-root cwd invariant for codex spawns (§3).

Two of these — the preamble and the disclaimer — are prompt text doing mechanical work.
Both were measured, and both fail silently and backwards when weakened. Whoever edits that
part of the corpus should re-run the conflict trials before shipping the change.
