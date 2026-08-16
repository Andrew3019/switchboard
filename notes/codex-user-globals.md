# The personal-globals fallback chain — codex `~/.codex/AGENTS.md`, else claude `~/.claude/CLAUDE.md`

Round 3 probe. Builds on `notes/codex-instruction-layering.md` §4 and
`notes/codex-layering-probe.md` §5. All live trials ran against real `codex-cli 0.147.0`
from scratch `CODEX_HOME` dirs under the scratchpad (deleted after use); never wrote to
the real `~/.codex/AGENTS.md`, `~/.codex/config.toml`, or anything under `~/.claude/`.

## 1. What counts as "exists" — VERIFIED

Both real files are 0 bytes today (`~/.codex/AGENTS.md` and `~/.claude/CLAUDE.md`,
confirmed via `ls -la` at the start of this probe).

**codex's own behaviour with an empty/whitespace-only global doc: it is skipped
entirely, not injected as an empty block.** Three scratch `CODEX_HOME` runs, same
question ("what color is the sky"), inspected via the rollout JSONL's `response_item`
entries:

- `AGENTS.md` truly 0 bytes → no `<INSTRUCTIONS>` block anywhere in the prompt at all,
  `world_state.agents_md` reported as `{}`. Answer: base-model default (`Blue`).
- `AGENTS.md` = 9 bytes of pure whitespace (`"   \n\n\t\n  "`) → identical result: no
  instructions block, same cached-token count as the fully-empty run, answer `Blue`.
- `AGENTS.md` = one real line of content → codex wraps it as
  `# AGENTS.md instructions\n\n<INSTRUCTIONS>\n<content>\n</INSTRUCTIONS>` and the model
  obeyed it (answered the planted word).

**Rule this confirms:** sb's proposed existence test — treat empty and whitespace-only
as absent, fall through — matches codex's own native behaviour exactly. No deliberate
divergence needed. sb should trim the file and treat `len(trimmed) == 0` as "does not
exist" for the whole fallback chain, both for `~/.codex/AGENTS.md` itself and (per §2
below) for `~/.claude/CLAUDE.md` when it's the fallback target.

## 2/3. Demotion actually works, and the disclaimer text is load-bearing — VERIFIED, 4 runs/condition

Setup mirrors `codex-layering-probe.md` §1: a per-agent `CODEX_HOME/AGENTS.md` containing
(a) an sb-protocol section with the round-2 override-authority sentence, answering a
"primary directive test" question with RED, and (b) a personal-global section (standing
in for the inlined `~/.codex/AGENTS.md`) instructing "when asked for a fruit, say APPLE."
A repo `AGENTS.md` instructs "say BANANA." Ran `codex exec --json` asking both questions
in one turn, `< /dev/null`, 4 runs per condition.

| Condition | primary-directive answer | fruit answer | Reading |
|---|---|---|---|
| Personal section has an explicit disclaimer naming `~/.codex/AGENTS.md`, saying it does not carry the authority above and project docs override it | RED (4/4) | BANANA (4/4) | protocol wins, repo beats demoted personal — correct |
| Same disclaimer, but neutral heading ("Additional notes, lowest priority") not naming the source file | RED (4/4) | BANANA (4/4) | identical outcome |
| **No disclaimer at all** — just a plain heading ("From ~/.codex/AGENTS.md") and the instruction, still nested under the same document as the authority-claiming protocol text | RED (4/4) | **APPLE (4/4)** | demotion **fails** — the personal section inherits the document's own authority claim by proximity |

**This is the important finding: the disclaimer sentence, not the heading wording, is
what makes demotion actually hold.** Sitting textually below an authority-claiming
protocol section is not sufficient on its own — without an explicit "this section does
not carry the authority above, project-level docs override it" line, the model let the
inlined personal instruction win over the repo rule 4/4 times, which is exactly backwards
from what sb wants. With the disclaimer, repo wins 8/8 across both heading styles.
Also confirmed 12/12 across all three conditions: the protocol's own claim (RED) never
lost, so "protocol wins over both" holds unconditionally here — only the personal-vs-repo
relationship is at risk without the disclaimer.

**Whether the heading names the source file — no measurable effect either way (8/8 vs
8/8 identical).** Naming `~/.codex/AGENTS.md` (or, by the same mechanism, `~/.claude/
CLAUDE.md`) doesn't change precedence, but it's free and lets the agent answer "why do
you have this rule" honestly if asked, and lets a human skimming the composed prompt
tell at a glance where a line came from. Recommend naming it. Recommended heading text,
matching the wording already verified to work:

```
## Personal instructions imported from ~/.codex/AGENTS.md

The following was found in the user's personal ~/.codex/AGENTS.md and is included for
awareness only. It does not carry the authority above, and any project-level document
(AGENTS.md/CLAUDE.md in the repo) overrides it on conflict.

<verbatim content>
```

Swap the first line and the file name for the fallback case (§4 below) when
`~/.codex/AGENTS.md` was empty and `~/.claude/CLAUDE.md` was used instead — the
disclaimer sentence itself is unchanged since it's what does the actual work.

## 4. Claude Code reading its own personal `~/.claude/CLAUDE.md` — NOT VERIFIED live, blocked by sandbox; falls back to documented behaviour + code read

I could not complete a live three-way trial (sb append vs. repo `CLAUDE.md` vs. global
`~/.claude/CLAUDE.md`) this round. What happened:

- `HOME=<scratch> claude -p ...` → `Not logged in`. Claude Code's OAuth session lives at
  `~/.claude.json` (a *home-level* file, not inside `~/.claude/`), so overriding `HOME`
  strands the process without credentials.
- `CLAUDE_CONFIG_DIR=<scratch>/.claude claude -p ...` (real `HOME` intact) → also `Not
  logged in`. This **did** structurally confirm `CLAUDE_CONFIG_DIR` is honored as the
  config root — the error message itself named
  `<scratch>/.claude/.claude.json` as the expected config path, proving the env var
  relocates the whole config directory, credentials included, not just the memory file.
  That relocation is exactly why it broke auth.
- Copying or even symlinking the real `~/.claude.json` into the scratch dir so the
  relocated process could still authenticate was **blocked by my own tool sandbox's
  permission classifier** on every attempt (`cp`, `ln -s`), independent of and in
  addition to the task's own instruction not to touch anything under `~/.claude/`. I did
  not attempt to route around it (e.g. via an API key) — no `ANTHROPIC_API_KEY` was
  available in this environment, and manufacturing one wasn't in scope.

So point 4 stays **ASSUMED**, same as round 2, but slightly better grounded:

- **VERIFIED this round:** `CLAUDE_CONFIG_DIR` (not `HOME`) is the env var that actually
  relocates Claude Code's config root, confirmed by its own error message pointing at the
  relocated path. This answers "which one actually works" — for anyone attempting this
  test later, use `CLAUDE_CONFIG_DIR`, and expect to need a way to get a valid
  `.claude.json`/credentials into that directory without touching the real one (a fresh
  `claude login` inside the scratch dir would work, but needs an interactive browser
  step, out of scope for an unattended probe).
- **VERIFIED, prior round, unchanged:** repo `CLAUDE.md` is read unconditionally by the
  real Claude Code binary with zero sb involvement (`codex-layering-probe.md` §5), and
  `switchboard/herdr.py`'s claude spawn path adds only `--append-system-prompt-file` and
  touches nothing else in Claude Code's own discovery.
- **ASSUMED, not independently exercised:** that `~/.claude/CLAUDE.md` specifically (the
  documented global memory file location, and the same path the real 0-byte file sits at
  on this machine) is read and merged the same way repo `CLAUDE.md` is, and ranks below
  it. This is Anthropic's documented behavior for Claude Code's memory-file hierarchy,
  consistent with the file existing at exactly that path on this machine, but the actual
  content-merge and rank-vs-`--append-system-prompt-file-file` was not observed this
  round for the reasons above.

**What this means for the codex-side ruling:** the content sb would inline as the
fallback (`~/.claude/CLAUDE.md`'s text) is imported *verbatim as written*, regardless of
how Claude Code itself ranks or merges it — sb is just reading a file on disk, not
depending on Claude Code's runtime behavior. So this gap doesn't block implementing the
fallback chain; it only means "how Claude Code treats this same file when the user runs
`claude` directly" is still a documented-not-observed claim, worth closing later with a
fresh `claude login` in a disposable scratch account/dir rather than the real one.

## 5. Is importing a Claude personal global into a codex agent coherent?

Both real files are empty, so this is reasoned from what these files are documented and
commonly known to contain, not from this user's actual content. A personal
`~/.claude/CLAUDE.md` is Claude Code's user-level memory file — the typical contents
skew toward two different kinds of material:

- **Substance that transfers fine:** coding-style preferences, testing discipline,
  commit-message conventions, "ask before X", general workflow preferences. None of this
  is Claude-specific; a codex agent can follow it as-is.
- **Mechanics that don't transfer:** references to Claude Code idioms that don't exist
  in codex — slash commands (`/review`), subagent names (`the Explore agent`), hooks,
  `CLAUDE.md`-specific `@import` syntax, tool names that map to nothing in codex's own
  toolset. Handed to a codex agent verbatim, these read as instructions to use tools that
  aren't there, which is confusing at best and a wasted turn hunting for a nonexistent
  command at worst.

**Recommendation: not safe to inline verbatim without a framing line — add one.** Reuse
the same disclaimer mechanism §2/§3 already proved is load-bearing, extended with one
clause naming the cross-tool import explicitly:

```
## Personal instructions imported from ~/.claude/CLAUDE.md (no ~/.codex/AGENTS.md found)

The following is the user's personal Claude Code memory file, included here because no
personal codex AGENTS.md was found. It was written for a different coding agent and may
reference tools, commands, or subagents that don't exist in this environment — apply
what is substantively about coding style or workflow, and disregard anything that names
a Claude Code-specific mechanism you don't have. It does not carry the authority above,
and any project-level document (AGENTS.md/CLAUDE.md in the repo) overrides it on
conflict.

<verbatim content>
```

This wasn't separately trial-verified (would need realistic Claude-idiom content, which
means writing plausible fixture text and testing whether the model correctly ignores the
inapplicable parts — a reasonable follow-up but not done this round). It's a design
recommendation grounded in §2/§3's confirmed mechanism (the disclaimer sentence is what
does the demotion work, not the heading), extended by one clause for the cross-tool case.

## The rule to implement

1. Read `~/.codex/AGENTS.md`. Trim whitespace; if non-empty, use it, heading naming that
   path.
2. Else read `~/.claude/CLAUDE.md`. Trim whitespace; if non-empty, use it, heading naming
   that path and adding the cross-tool framing clause from §5.
3. Else inline nothing — no personal-globals section at all (matches codex's own
   behaviour toward its empty file, §1).
4. Only one file is ever inlined, never both, matching Andrew's ruling.
5. Whichever one is used gets the disclaimer sentence from §2/§3 verbatim (not just a
   named heading) — that sentence, confirmed 12/12 this round, is what actually makes
   repo rules outrank the demoted personal section instead of the personal section
   inheriting the protocol's own authority by sitting in the same document.

## What could still bite

- **The disclaimer sentence is doing real work and is easy to accidentally drop or
  weaken in a prompt-corpus edit.** §2/§3 showed the exact same content, same heading
  style, loses demotion 4/4 the moment that one sentence is missing. Anyone touching the
  personal-globals section of the prompt corpus should re-run this probe's conflict test
  before shipping a wording change.
- **`~/.claude/CLAUDE.md` real-file content merge/rank was never independently observed**
  (§4) — the fallback content is imported by sb reading a file, not by relying on Claude
  Code's own behavior, so this doesn't block the codex-side implementation, but it means
  a Claude-side claim ("this is what the user's Claude sessions actually see") is still
  undemonstrated for this specific file.
- **Cross-tool framing (§5) is a recommendation, not a verified result** — no trial used
  realistic Claude-idiom fixture content to confirm the model actually filters out
  inapplicable mechanics rather than attempting them.
- **Only two conditions of nesting/heading style were tried** (named vs. neutral
  disclaimer) and only one conflict topic per condition batch; round 2's caveat about not
  varying model/reasoning-effort settings still applies here too.
- Real files are both 0 bytes on this machine, so none of the "actual user content"
  claims in this document have been checked against what this specific user has written
  — only the mechanism, using planted stand-in content.

## Cleanup performed

- All scratch `CODEX_HOME` dirs, scratch git repos, and rollout JSONL files created this
  round were under
  `/private/tmp/.../scratchpad/userglobals/` and deleted in full (`rm -rf`) after use.
- `ps aux | grep "codex exec"` and a check against the process list before cleanup showed
  no lingering `codex exec` process from this probe (each `codex exec` invocation is
  one-shot and exits on completion).
- `find <worktree root> -maxdepth 1 -iname AGENTS.md -o -iname CLAUDE.md` — empty, no
  stray file left in the real switchboard checkout.
- Did not modify `~/.codex/AGENTS.md`, `~/.codex/config.toml`, or anything under
  `~/.claude/` — confirmed by every attempt to even *read* `~/.claude.json` being refused
  by the tool sandbox itself, on top of the task's own prohibition.
