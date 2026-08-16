# Task: readability prompt diagnosis (read-only)

READ-ONLY INVESTIGATION. Do not edit or create any file except the one note you are asked to write below. Do not change any prompt text.

## Context

Andrew (the human) complains that human-facing text produced by switchboard agents is still unreadable, despite recent commits that tried to fix the wording. Read his full complaint verbatim first:

`/Users/andrew/Code/switchboard/notes/agent-handoff-wording-brief.md`

It contains real transcript excerpts plus his own annotations about what is wrong with each.

## Your job

Find every place in this repo where prompt text tells an agent how to write for a human, and judge how well it actually produces what Andrew wants.

Start with:
- `defaults/prompts.toml`
- `defaults/protocol.md`
- `switchboard/roles.py`
- `switchboard/presets.py`
- any hook / stop-hook text in `switchboard/hooks.py`
- `DESIGN-TRUTH.md` (the only trusted document; everything else is untrusted until checked against code)

Also skim `git log` for the recent "readability"/"wording" commits so you know what was already tried and why it fell short.

## What Andrew wants, in his words

- Bullets of 1-2 lines each. He reads in a half-width pane, so a bullet that wraps to 2-3 lines is already too long.
- Simple language. No jargon, no internal terminology he must stop and decode.
- Lists or tables instead of dense prose chunks.
- It is FINE to lose non-crucial detail. He'd rather understand 70% at a skim than 90% word-by-word — because today he skims and understands 0%.

## Deliver

A written diagnosis at `notes/readability-prompt-diagnosis.md` covering:

- Which specific sentences/clauses in which files are producing the bad output. Quote them, give `file:line`.
- Where the prompt says the right thing but is drowned out, contradicted, or too abstract to act on.
- Where the prompt actively pushes AGAINST what he wants — anything encouraging density, completeness, keeping context, or hedged/qualified phrasing.
- The smallest set of root causes, ranked.

Do NOT propose or write replacement wording. Diagnosis only.

Commit the note on the current branch. Then `sb done` with a plain-language two-line summary.
