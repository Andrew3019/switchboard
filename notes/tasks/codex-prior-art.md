# Research task — prior art: orchestrators/wrappers that drive both Claude Code and codex

WEB RESEARCH. No code changes. Write only your own notes file.

Context: switchboard (`sb`) is a multi-agent orchestrator that currently drives Claude
Code panes and is adding codex support. Read `notes/codex-support-findings.md` first so
you know what problems we already consider solved and which are open — the useful output
is what *other people* did about the same problems, not a restatement of ours.

Find and report on real projects that drive more than one agent CLI — multi-agent
harnesses, provider-abstraction layers, "run Claude and codex side by side" tools, agent
fleet managers, IDE/terminal multiplexers for agents. Include both well-known ones and
small ones; GitHub repos, blog posts, and docs all count.

For each, pull out concrete, citable specifics on the questions we actually face:

1. **The `CLAUDE.md` / `AGENTS.md` split.** How do they handle a repo that has one, the
   other, or both? Symlink? Generate one from the other? A single source file plus a
   build step? Ask the user? Is there any emerging convention (e.g. `AGENTS.md` as a
   cross-vendor standard, and who actually reads it)?
2. **Prompt portability.** Do they keep one prompt corpus and adapt delivery per provider,
   or maintain separate prompts? How do they handle the fact that Claude Code takes an
   appended system prompt and codex only takes a per-turn user-message doc?
3. **Per-agent isolation.** Do they use per-agent config homes (`CODEX_HOME`-style),
   worktrees, containers? How do they keep several agents in one checkout from colliding?
4. **Turn / done detection.** Screen scraping, hooks, exec-mode JSON streams, notify
   hooks, file watching? What proved reliable?
5. **Anything that bit them** — postmortems, issues, "why we dropped X" notes are more
   valuable than READMEs.

Also check whether OpenAI or Anthropic have said anything official about cross-reading
each other's rules files, and whether `AGENTS.md` has a spec or registry behind it.

Be honest about coverage: if the space is thin, say so plainly and show what you searched
rather than padding. Distinguish what you read from what you inferred, and cite every
claim with a URL. Prefer primary sources (repo code, docs, issues) over listicles and
AI-generated blogspam, and say when a source looks unreliable.

Deliverable: `notes/codex-prior-art.md`. You own that file and only that file. Structure
it by the five questions above, with a short "what we should steal / what we should
avoid" at the end. Commit on the current branch, then `sb done` with a two-line summary
leading with whether the space is thin or crowded.
