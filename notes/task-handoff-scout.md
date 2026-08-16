# Task: conversation-handoff prompt diagnosis (read-only)

READ-ONLY INVESTIGATION. Do not edit or create any file except the one note you are asked to write below. Do not change any prompt text.

## Context

Read Andrew's full complaint verbatim first:

`/Users/andrew/Code/switchboard/notes/agent-handoff-wording-brief.md`

The second half (from "followups are not good") is your subject. Real transcript is included.

## The problem, in Andrew's words

A dispatcher finished a run, blocked, and gave Andrew two leftover questions. Andrew asked for more context on both. The dispatcher then restored the two child agents that actually held the detail, asked them to explain, waited, and **relayed their answers back to Andrew itself**.

Andrew does not want that. What he wanted:

- Dispatcher restores the two agents.
- Dispatcher tells each of them to explain the specific thing, and to `sb block` so Andrew reads it directly.
- Dispatcher then marks itself `sb done`.
- Andrew talks to those two agents directly, in their own panes, back and forth.
- When he's finished with them, they `sb done` back up to their parent.

His words: "the dispatcher should avoid piping outputs between me and agents. this should be a design truth or principle somewhere."

Note the related failure: because the dispatcher relayed, the explanation Andrew got was second-hand and thin — he had no context to make a decision, so he was "either guessing or asking for more context".

## Your job

Find every place in the prompt text that governs this, and diagnose why agents behave as relays instead of handing the conversation over.

Start with:
- `defaults/prompts.toml`
- `defaults/protocol.md`
- `switchboard/roles.py` (especially the dispatcher and lead role text)
- `switchboard/presets.py`
- any hook / stop-hook text in `switchboard/hooks.py`
- `DESIGN-TRUTH.md` (the only trusted document; everything else is untrusted until checked against code)

Questions to answer concretely:

1. What does the prompt currently say about relaying, about being a "permanent proxy", about pointing the human at the child that owns the detail? Quote it with `file:line`. Why is it not working — too weak, too abstract, buried, or contradicted?
2. What in the prompt actively pushes an agent toward relaying? Look at anything telling a parent to synthesise children's work, to be the reader's single voice, to translate children's vocabulary, or forbidding a child from reaching a human.
3. Is the handoff Andrew describes even mechanically expressible today? Check the actual `sb` verbs in the code: can a parent instruct a child to `sb block` for a human? Can a child that was blocked and then answered by a human report back up and finish? Does `sb done` by a parent while children are blocked leave those children reachable and alive? Does anything in cleanup/close logic kill a blocked child when its parent finishes? Read the code, do not trust the docs.
4. What is missing entirely — the rule, principle, or verb that would have to exist for the intended flow to be the obvious one.

## Deliver

A written diagnosis at `notes/handoff-prompt-diagnosis.md` covering the four questions above, ending with the smallest set of root causes, ranked, and a clear statement of which are prompt-wording problems versus missing mechanism in the code.

Do NOT propose or write replacement wording, and do not implement anything. Diagnosis only.

Commit the note on the current branch. Then `sb done` with a plain-language two-line summary.
