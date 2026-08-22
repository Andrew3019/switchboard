# Prior art — running Claude Code and codex side by side

Web research only; no code touched. Read against `notes/codex-support-findings.md` (our
own probe results) so this only reports what *other people* did, not a restatement.

**Coverage note up front:** the space is thin at the "we solved the same seam problems
you did" level and crowded at the "generic multiplexer that shells out to N CLIs" level.
Most hits are wrapper projects that treat each provider as an opaque PTY and don't
publish anything about the specific mechanisms we're worried about (prompt delivery
semantics, hook trust, per-agent config homes). The two genuinely load-bearing sources
found are: Anthropic's own memory docs (official, authoritative, directly answers Q1),
and a cluster of `openai/codex` GitHub issues/discussions (primary source, directly
answers Q2 and Q5). Everything else is secondary — READMEs and blog posts, several of
which are 2026-vintage SEO content of uncertain reliability, flagged below where used.

All content below is via `WebSearch`/`WebFetch` — I did not clone or run any of these
projects, only read what their docs/pages/issues state.

## 1. The `CLAUDE.md` / `AGENTS.md` split

**Official Anthropic position, primary source**
(https://code.claude.com/docs/en/memory, fetched in full): "Claude Code reads
`CLAUDE.md`, not `AGENTS.md`... no automatic fallback." Anthropic's own recommended
patterns for a repo that already has `AGENTS.md`:
- a one-line `CLAUDE.md` containing `@AGENTS.md` (their import syntax), optionally with
  Claude-specific content appended below it, e.g.:
  ```
  @AGENTS.md

  ## Claude Code
  Use plan mode for changes under `src/billing/`.
  ```
- or a plain symlink, `ln -s AGENTS.md CLAUDE.md` (noted as not working on Windows
  without admin/Developer Mode — use the import there instead)
- `/init` (with `CLAUDE_CODE_NEW_INIT=1`) now reads `AGENTS.md` itself when generating a
  new `CLAUDE.md`, alongside Cursor/Copilot/Devin/Windsurf/Cline rule files
- `/import` (Claude Code ≥2.1.213) does a **one-time copy**: appends `AGENTS.md` content
  into `CLAUDE.md` and also carries over MCP servers, commands, subagents, and skills

So Anthropic has picked a stance: don't read `AGENTS.md` natively, but make importing it
trivial and machine-assisted. This is a real, current, first-party answer to "does Claude
Code cross-read the other vendor's rules file" — no, deliberately, with blessed
workarounds.

**`AGENTS.md` governance (secondary sources, not independently verified beyond the spec
site's own claim).** The format is described as emerging around August 2025 from OpenAI
Codex, Amp, Google Jules, Cursor, and Factory jointly, and as now "stewarded by the
Agentic AI Foundation" under the Linux Foundation (per agents.md itself, fetched). I did
not verify the Linux Foundation project registration independently — treat that
governance claim as "the spec site says so," not confirmed elsewhere. The spec itself is
deliberately unopinionated: "AGENTS.md is just standard Markdown... the agent simply
parses the text you provide," and it defines only file discovery (closest file wins in a
monorepo), not schema. It says nothing about `CLAUDE.md` interop at all — that's a
Claude-side concern, not something the spec addresses.

**Community convention, secondary source**: SSW.Rules
(https://www.ssw.com.au/rules/symlink-agents-to-claude) documents the symlink pattern as
a house rule independent of Anthropic's docs, suggesting it's become a genuine community
default rather than something only Anthropic suggests.

**What a real multi-CLI orchestrator does differently**: `awslabs/cli-agent-orchestrator`
(CAO) doesn't symlink or import at all. Per its docs (fetched:
https://github.com/awslabs/cli-agent-orchestrator/blob/main/docs/codex-cli.md), it
injects generated content into *both* files independently, each via its own
delimited-block plugin: "the plugin owns **only** the delimited block and replaces it in
place on each run — any hand-written content around it is preserved (the same approach
as the Claude Code `CLAUDE.md` plugin)." So CAO treats `CLAUDE.md` and `AGENTS.md` as two
separate write targets it manages a fenced region of, rather than unifying them. This is
the opposite of the symlink/import convention above — worth noting as a live design
choice, not just an oversight, since CAO is actively maintained and presumably hit real
reasons to keep them separate (most likely: it doesn't want to force a repo-level
`AGENTS.md`↔`CLAUDE.md` coupling decision onto users who only run one of the two tools).

## 2. Prompt portability

Anthropic's own equivalent of "one prompt corpus, provider-specific delivery" is
`--append-system-prompt`, documented as something that "must be passed every invocation,"
i.e. Anthropic itself treats re-supplying standing instructions per-run as the
correct pattern for scripted/automation use, not a one-time system message — the same
shape as our per-turn `CODEX_HOME/AGENTS.md` delivery, just via a flag instead of a file.
That's a mild point of external validation for our approach's *shape* (re-deliver every
turn), even though the underlying mechanism differs.

**CAO's approach**: keeps one prompt corpus per agent profile (a `system_prompt` field in
profile markdown) and adapts *delivery* per provider — this matches our own finding that
composition is provider-agnostic and only delivery differs. For codex specifically, CAO's
docs claim it passes the prompt via `-c developer_instructions="<prompt>"` at launch, and
say this is "per-session... nothing is written to the user's global `~/.codex/config.toml`."
This is a materially different delivery mechanism from our `CODEX_HOME/AGENTS.md`
approach: an inline CLI config override with zero filesystem footprint at all (not even a
private directory), versus our private-directory-with-a-file approach.

I could not confirm `developer_instructions` from codex's own official config reference
(`docs/config.md` in `openai/codex`, fetched — it isn't listed there), so I went to
primary sources to check whether CAO's docs are describing something real:

- **openai/codex discussion #7296** ("Pro Tip: Use a custom system prompt with codex"),
  primary source, fetched: confirms **two distinct, both real but neither
  fully-documented** mechanisms:
  - `-c experimental_instructions_file=<path>` — **replaces the entire base system
    prompt**. Confirmed working by a commenter after fixing a typo. The `experimental_`
    prefix is OpenAI's own naming, i.e. explicitly unstable/subject-to-change.
  - `-c developer_instructions="<string>"` — this is what CAO uses. A commenter
    (kevin-valerio) is explicit that this is **not** a system prompt: it's "some
    additional user instructions appended after AGENTS.md." So CAO's docs, read plainly,
    overstate what this does — it's not a role-elevated developer message, it's more
    prompt text stacked after the project's `AGENTS.md`, functionally adjacent to (not
    better than) the `AGENTS.md` channel we're already using.
- **openai/codex issue #12926** ("Add `developer_instructions_file` for stronger local
  guidance"), primary source, fetched: someone asked OpenAI directly for a *file-based*
  version of `developer_instructions` because "guidance in `AGENTS.md` is not always
  followed consistently enough for strict workflows," whereas developer-role instructions
  showed "much better adherence." **Closed as not planned**, labels `config`,
  `enhancement`, no visible maintainer rationale in the issue body. Read plainly, this is
  the closest thing to an official OpenAI signal on the question "is there a
  stronger-than-`AGENTS.md` instruction channel coming": they were asked for one and
  declined it. That's mild validation that `AGENTS.md`-as-standing-instructions (our
  `CODEX_HOME` approach) is the channel OpenAI intends people to use, not a stopgap.

Net: our `CODEX_HOME/AGENTS.md` approach and CAO's `-c developer_instructions=` are two
different answers to the same delivery problem, and CAO's is *not* a stronger channel
despite how its docs frame it — it's the same authority level as `AGENTS.md`, just
inline instead of file-based, and per-session instead of per-agent-home. Nobody found in
this search has documented anything that reaches system-prompt-level authority reliably
and non-experimentally in codex.

## 3. Per-agent isolation

Thin. Nobody documents a `CODEX_HOME`-as-private-per-agent-directory pattern at the
granularity we found (private home + pre-seeded trust + private `auth.json` question).
What exists:

- **CAO**: per-session config scope via `-c` overrides only ("nothing is written to the
  user's global `~/.codex/config.toml`"), each agent CLI in its own tmux session. This
  sidesteps the isolation problem rather than solving the same one we have — it never
  needs a private `CODEX_HOME` because it never writes standing config at all, trading
  that for the weaker `developer_instructions=` channel from Q2.
- **Generic guidance** (multiple secondary sources on "run multiple codex agents"):
  one git worktree per agent is the universal recommendation for filesystem isolation;
  a few sources go further and recommend one OS user / one home directory per agent for
  credential isolation, which is structurally the same move as our `CODEX_HOME` idea but
  described at OS-account granularity rather than as a lightweight per-agent env var.
  These are all secondary/blog sources of moderate reliability — no primary-source
  confirmation that anyone runs this in production at fleet scale.

I read this as: switchboard's `CODEX_HOME`-per-agent approach is ahead of documented
prior art here, not behind it. That's worth stating plainly rather than implying we
missed some existing pattern.

## 4. Turn / done detection

This is where the most useful — and most cautionary — material showed up.

**Screen scraping, and why one project has to hedge it**: CAO's provider layer
(https://github.com/awslabs/cli-agent-orchestrator/blob/main/docs/codex-cli.md, fetched)
does pattern-matching on terminal output and openly documents needing **two different
output-format matchers** — a "Label style" format for its own synthetic/test harness and
a "Bullet style" format for real interactive codex — to recognize the same states
(`IDLE`/`PROCESSING`/`WAITING_USER_ANSWER`/`COMPLETED`/`ERROR`). That's a maintained
project admitting, in its own docs, that PTY-output matching is fragile enough to need
format-specific branches. This is exactly the class of mechanism our own findings avoid
by using codex's native `hooks.Stop`.

**A structured alternative that exists but doesn't cover Claude Code natively**: the
Agent Client Protocol (ACP), via the `ACPX` client
(https://casys.ai/blog/acpx-multi-agent-orchestration, fetched, blog-quality secondary
source but with concrete technical claims). ACP replaces PTY scraping with JSON-RPC over
stdio and an explicit `initialize → session → prompt → streamed updates → cancel`
lifecycle, so "done" is a real message, not an inferred terminal state. Two caveats
worth carrying forward: (1) "Claude Code does not currently expose a native ACP server
command" — confirmed further by a mention that Anthropic closed the corresponding GitHub
issue (#6686, not independently fetched by me) as **NOT_PLANNED**, so ACP support for
Claude Code exists only via a community-maintained adapter, a real dependency risk; (2)
codex does support ACP-shaped output more natively via `codex exec --json`, which emits a
typed event stream (`thread.started`, `turn.started`, `turn.completed`/`turn.failed`,
`item.completed` with `item.type = "agent_message"` for the final answer) — this is a
cleaner, more granular signal than a Stop hook if sb ever needs mid-turn progress instead
of just end-of-turn, though it's `exec`-mode only, not the interactive TUI we're piping
into a pane.

**A concrete postmortem on why raw stdout/exit-code is not enough** —
`openclaw/openclaw` issue #65074 (fetched, primary source, a real bug report against a
project that drives `codex-cli`): they found stdout "can contain progress-oriented or
transport-oriented output rather than the clean final answer," that "exit code alone is
not enough to determine semantic success/failure," and specifically that "Codex may still
exit 0 while the failure only appears in output content" — so a naive
stdout-parse-plus-exit-code integration silently treats failed runs as successful. Their
fix: use `--output-last-message <file>` as the single authoritative source for the final
reply, and demote stdout/JSONL to telemetry-only. This directly reinforces our own
decision to use `hooks.Stop` rather than parsing output, and separately suggests
`--output-last-message` as a candidate mechanism if sb ever needs codex's final answer
text specifically (as opposed to just knowing a turn ended) — worth a note for whoever
builds the rollout-transcript reader item in our own findings' "what has to be built"
list, since it may be a cheaper source of "the last thing codex said" than parsing the
rollout JSONL.

## 5. Anything that bit them

- **`openai/codex` issue #37937** ("A repeatedly blocking Stop hook can trap Codex CLI in
  an infinite no-escape loop"), fetched, primary source, open at time of writing, no
  maintainer response visible. Root cause: a `Stop` hook that keeps returning the same
  block (in the reported case, because a dependency it shells out to had moved/broken)
  causes codex to keep generating new turns forever with no user escape path — "Codex
  must not create an unbounded automatic loop when the same hook returns the same block
  repeatedly without new user input or measurable progress." The issue explicitly notes
  codex does **not** currently distinguish "hook infrastructure failure" from
  "intentional policy denial," and asks for a re-block cap and an explicit escape path.
  This is a direct, unresolved analogue of our own finding that a real turn "blocked and
  re-opened 11x" — that wasn't sb-specific behavior, it's a documented open codex gap.
  **This is worth treating as a hard requirement before shipping our own `Stop` gate**:
  our `hooks.py` enforcement needs its own re-block cap, because codex's anti-loop
  protection (`stop_hook_active`) is not proven to prevent this class of failure and this
  issue suggests it doesn't.
- **`openai/codex` issue #22858** ("Clarify or fire Stop hook when a turn is interrupted
  with Esc"), fetched, primary source: the `Stop` hook does not appear to fire when a
  user interrupts a turn mid-flight (e.g. Esc). Relevant if sb or a human ever cancels an
  agent turn out-of-band — the done-gate may simply not fire on that path, which would
  look like a hang rather than a completed-but-ungated turn.
- **`openclaw` #65074**, already covered above under Q4 — a real "why stdout parsing bit
  us" report.
- Two historical discussions (`openai/codex` #14203 and #14219, surfaced by search but
  not fetched in full — titles: "If you really want stop hooks in Codex, here's something
  I tried") suggest `hooks.Stop` support in codex was itself community-requested and
  hand-rolled via a local fork before OpenAI shipped it natively. Not fetched for detail;
  flagging only as a pointer if the group wants pre-native-hooks history.

## What we should steal / what we should avoid

**Steal:**
- Anthropic's `@AGENTS.md` import pattern is the officially blessed answer if switchboard
  ever needs a *repo-visible* instruction file for some reason — we currently avoid this
  entirely via `CODEX_HOME`, and that avoidance looks correct in light of Q1, but if a
  future requirement needs repo-visible instructions, import > symlink > hand-sync.
- `--output-last-message <file>` (codex `exec`) as a cheap source of "the final answer
  text," decoupled from parsing the rollout JSONL — relevant to the still-unbuilt
  transcript reader in our own findings.
- Put a hard re-block cap in our own `hooks.py` Stop-gate logic before shipping. Issue
  #37937 is not theoretical — it's an open, unresolved codex bug, and our own probe
  already reproduced the shape of it (11 blocks on one real turn).

**Avoid:**
- CAO's `-c developer_instructions=` framing as a "developer-role" prompt channel — per
  the primary-source discussion, it is not elevated authority, just text appended after
  `AGENTS.md`. Don't build on the assumption it's stronger than what we already have.
- `-c experimental_instructions_file=` for anything beyond throwaway experiments — it's
  OpenAI's own "experimental" label, replaces the whole system prompt (not additive), and
  has no documented stability guarantee.
- PTY output pattern-matching for done detection, per CAO's own admission that it needs
  format-specific branches to stay reliable. Our `hooks.Stop` approach is already the
  better mechanism found anywhere in this search, including outside our own probes.
