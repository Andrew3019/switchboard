# Probe task — the full instruction-layering stack, verified against the real codex binary

INVESTIGATION + EXPERIMENT. No switchboard code changes. Write only your own notes file.

Read first, and do not re-verify what they already settled:
`notes/codex-support-findings.md` (the round-1 synthesis) and its five source notes,
especially `notes/codex-probe-prompt-channel.md`.

## The scenario to protect

A user already runs Claude Code on their project and has a repo `CLAUDE.md`. They adopt
`sb`. They then add codex agents through `sb`. **Nothing may regress at any layer.** In
particular a codex agent spawned by sb must still inherit that repo `CLAUDE.md`, and the
sb protocol must not lose authority to repo-level rules.

## What to establish, with live evidence

Build a precedence model covering every instruction source that can be in play:

- repo `CLAUDE.md` (and nested ones), repo `AGENTS.md` (and nested ones)
- the user's own globals: `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`
- sb's composed prompt (protocol + role + presets), delivered per-provider
- anything in `CODEX_HOME/AGENTS.md` and `CODEX_HOME/config.toml`

Answer these by running codex, not by reasoning:

1. **Ordering vs authority.** Round 1 showed codex concatenates global doc first, then a
   `--- project-doc ---` marker, then the project doc. Ordering is not precedence: put
   *directly contradicting* instructions in the two slots and find out which one the model
   actually follows. Repeat a few times, and with the conflict stated at different
   strengths. This is the precedence-inversion question and it is the crux — the sb
   protocol must win.
2. **Can repo `CLAUDE.md` be inherited natively?** Round 1 established
   `project_doc_fallback_filenames` reads a differently-named repo file as the project
   doc, but only when `AGENTS.md` is absent. Test setting it from a private
   `CODEX_HOME/config.toml` to include `CLAUDE.md`. Determine exactly: does it work from
   `CODEX_HOME` config; is it ordered (first match wins, or all merged); what happens when
   both `AGENTS.md` and `CLAUDE.md` exist; can the list contain both so either is picked
   up. Also test the alternative — sb reading repo `CLAUDE.md` itself and inlining its
   text into `CODEX_HOME/AGENTS.md` — and say which is better and why.
3. **Truncation interaction.** `project_doc_max_bytes` (default 32768) truncates the
   project doc silently, mid-line, with no warning. Establish what happens with a large
   repo `CLAUDE.md` under each of the two approaches in (2) — does inlining into the
   global doc escape the cap (round 1 suggests yes up to 35KB; push further, find the real
   ceiling or establish there isn't one), and can `project_doc_max_bytes` simply be raised
   in `CODEX_HOME/config.toml`?
4. **Nested docs.** Round 1 left this open: do nested `AGENTS.md`/`CLAUDE.md` files
   further down the tree get merged, in what order, and relative to the global doc? Test
   with the cwd at the repo root and in a subdirectory.
5. **The user's own globals.** A private per-agent `CODEX_HOME` means `~/.codex/AGENTS.md`
   is no longer read — name this as a regression and determine whether sb should inline it
   (verify whether it is read at all when `CODEX_HOME` is default, and whether it merges
   with repo docs and in what order). Same question for `~/.claude/CLAUDE.md` on the
   Claude side: confirm whether an sb-spawned claude agent reads repo `CLAUDE.md` and the
   user's global today (check how sb spawns claude — `herdr.py:557-580` — and verify in a
   real pane if you can do so without disturbing the live fleet).
6. **Leakage.** Confirm the failure mode sb must avoid: an `AGENTS.md` written into the
   repo would be picked up by the human's own codex sessions and by every other agent
   sharing the worktree. State whether the `CODEX_HOME` design fully avoids it, including
   for `project_doc_fallback_filenames` (does pointing at `CLAUDE.md` have any side effect
   on a human's own codex run? it shouldn't — the config is private — verify).

## Deliverable

`notes/codex-layering-probe.md`. You own that file and only that file. Give a single
precedence table per provider (claude, codex) listing every layer in force order, and a
named list of failure modes with whether the design avoids each. Exact commands and real
output; mark verified vs assumed. Do not write the final recommendation — the lead
synthesises that; give the evidence and the model.

Scratch dirs and private `CODEX_HOME`s only; never modify the real `~/.codex/config.toml`
or `~/.claude/`; delete every session (`codex delete --force <id>`); no unscoped `pkill`.
Commit on the current branch, then `sb done` with a two-line summary leading with which
layer wins when the sb protocol and a repo doc conflict.
