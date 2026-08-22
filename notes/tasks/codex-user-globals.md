# Probe task — the personal-globals fallback chain for codex agents

INVESTIGATION + EXPERIMENT. No switchboard code changes. Write only your own notes file.

Read first: `notes/codex-instruction-layering.md` §4 and `notes/codex-layering-probe.md`
§5.

## The ruling to implement

A private per-agent `CODEX_HOME` drops the user's own `~/.codex/AGENTS.md`, so sb inlines
it into the per-agent `AGENTS.md`, demoted below the protocol and below repo rules.

Andrew has extended this: it is a **fallback chain at the personal level, mirroring the
repo level**. Use `~/.codex/AGENTS.md` if present and non-empty; otherwise fall back to
`~/.claude/CLAUDE.md`. **Only one is ever inlined, never both.**

## What to work out and verify

1. **What counts as "exists".** Both real files are 0 bytes on this machine, which is
   exactly the live case. Establish the rule: treat empty (and whitespace-only) as absent,
   so a 0-byte `~/.codex/AGENTS.md` falls through to `~/.claude/CLAUDE.md`. Check what
   codex itself does with an empty global doc — does it inject an empty `<INSTRUCTIONS>`
   block, skip it, or something else? That tells us whether sb's rule matches codex's own
   behaviour or deliberately differs.
2. **Verify the demoted inline actually behaves as demoted.** Put a personal-global rule
   into the inlined section and a conflicting repo rule in the project doc; confirm the
   repo rule wins, and that the protocol still wins over both. Use the same conflict setup
   as `codex-layering-probe.md` §1. Several runs per condition.
3. **Does the demotion heading need to name the source file?** Test both — a neutral
   heading vs one naming `~/.codex/AGENTS.md` / `~/.claude/CLAUDE.md`. Consider whether
   naming it helps the agent reason about precedence, or just leaks a path. Recommend one,
   with the trials behind it.
4. **Close the ASSUMED gap from round 2.** It was never verified that Claude Code actually
   reads `~/.claude/CLAUDE.md` and how its content merges, because the real file is empty
   and off-limits. Verify it with a **scratch stand-in** — run `claude` with `HOME` (or
   `CLAUDE_CONFIG_DIR`, whichever actually works — determine which) pointed at a scratch
   directory containing a global `CLAUDE.md`, and observe whether its content applies and
   how it ranks against a repo `CLAUDE.md` and against `--append-system-prompt-file`. This
   matters because it tells us what we are importing when we inline it for codex.
5. **Is importing a Claude personal global into a codex agent actually coherent?** Look at
   what such a file typically contains (tool-specific instructions, slash commands, Claude
   idioms). Say plainly whether inlining it verbatim is safe, or whether it should carry a
   framing line telling the agent it came from another tool and to apply only what
   transfers. Recommend exact wording if so.

## Deliverable

`notes/codex-user-globals.md`. You own that file and only that file. Give: the precise
existence/fallback rule, the exact heading and any framing text sb should write, the
verification of point 4, and a short list of what could still bite. Mark verified vs
assumed.

**Never write to the real `~/.codex/AGENTS.md`, `~/.codex/config.toml`, or anything under
`~/.claude/`** — scratch stand-ins only. Delete every session (`codex delete --force
<id>`); no unscoped `pkill`. Commit on the current branch, then `sb done` with a two-line
summary leading with the existence rule and whether the Claude-global import is safe.
