# Task: design a complexity-tiered budget for human-facing bullets (proposal only)

PROPOSAL ONLY. Do not edit any prompt file, any role file, `defaults/protocol.md`,
`defaults/prompts.toml`, or `DESIGN-TRUTH.md`. Your entire output is one new note.

## Background — read these first, in order

1. `/Users/andrew/Code/switchboard/notes/agent-handoff-wording-brief.md` — Andrew's original
   complaint, verbatim, with real transcript excerpts he annotated.
2. `notes/readability-prompt-diagnosis.md` — the diagnosis already done. Do not redo it.
3. `DESIGN-TRUTH.md` — the human-facing output section (~lines 180-230) and its stated
   reason for having no length limit.
4. `defaults/protocol.md` — the human-facing output paragraph (~lines 240-260).

Andrew reads his agent panes at **half screen width**. A bullet that wraps to three lines
is already too long for him. He has said he'd rather understand 70% at a skim than 90%
word-by-word, because today he skims and understands 0%.

## What Andrew decided

He has approved adding a length budget, overriding DESIGN-TRUTH's current "no word or line
limit, ever" stance. His words:

> "yes. consider both a line budget and a word count budget for bulletpoints. but this
> should have some dynamicness to this.
>
> in my own manual prompting, i often say output as bulletpoints, max 15 words each.
> sometimes 10. sometimes 20. depends on how complex the situation is. so can we
> investigate adding something similar, where we have preset budgets, but the agent will
> pick which complexity it is? this way it has to pick complexity which maps to a budget,
> instead of picking max budget and justifying why"

The design intent is the important part: **the agent names the situation, and the situation
determines the number.** It must never choose a number directly, because choosing a number
directly always resolves upward with a justification attached.

## What to design

### 1. The tier scheme (the core of the job)

- How many tiers? Andrew's own instinct is roughly 10 / 15 / 20 words. Treat that as a
  starting point, not a constraint — argue for what you actually think is right.
- What is each tier *named*, and what situation does it describe? The name must be
  recognisable from the outside: an agent should be able to look at what it is about to
  say and know which tier it is, without weighing its own preference.
- The discriminator must be a property of **the subject matter**, not of the writer's
  judgement about how much it wants to say. "This is complicated" is self-serving and
  gameable. Find discriminators that aren't.
- Does the tier apply per message, or per bullet? Argue it. A message may mix a one-line
  status with a genuinely intricate finding.

### 2. The line budget, alongside the word budget

- Andrew asked for both. Work out what a line budget adds that a word budget doesn't —
  they are not the same constraint at half-pane width, and one of them is the one he can
  actually see violated.
- Decide whether the line budget is the hard one and the word budget the guide, or the
  reverse.

### 3. Anti-gaming

This is the part most likely to fail in practice. Address it directly:

- What stops an agent classifying nearly everything into the loosest tier?
- Is there a stated default tier — i.e. "most messages are the smallest one, and reaching
  for a larger tier is the unusual move"?
- Is there a cost or a check attached to the loosest tier that makes it self-limiting?
- What does an agent do when a fact genuinely will not fit its tier? (Splitting into two
  bullets, nesting a sub-bullet, and pointing at a file path are all candidate answers —
  say which, and whether that escape hatch reopens the gaming problem.)

### 4. The other readability faults, same section of prompt

The diagnosis found three more that a budget alone will not fix. Design wording for each:

- **No ceiling on cutting.** The only cut rule today is a floor — "keep it if removing it
  would change what the reader does next". Nothing tells an agent to actively prefer fewer,
  coarser claims. Andrew's tolerance for losing detail is much larger than the prompt's,
  and only the prompt's is written down.
- **One bullet, many ideas.** Nothing says a bullet holds one idea. Two ideas welded with a
  dash or semicolon is currently legal and is exactly the shape Andrew keeps receiving.
- **The overloaded single line.** His clearest example — `Merged: #55 worktree leak · #56
  cleanup aliveness · #57 …`, eight facts on one line — is invisible to every rule we have,
  because they all talk about bullets and paragraphs. He explicitly said this wanted to be
  a table or a list. Design the rule that catches it.

### 5. The DESIGN-TRUTH collision

`DESIGN-TRUTH.md` currently forbids exactly what Andrew has now approved, and states a
reason: a number becomes a mould that gets pattern-matched and gamed. **Only Andrew edits
that file.** So:

- Write the replacement passage as a *proposal for him to paste*, clearly marked as such.
- It must engage with the original reason rather than deleting it. Explain, in the text
  itself, why a tiered budget is not the mould the old rule feared — or, if you conclude it
  *is*, say so plainly and argue the trade anyway.
- Per the standing rule on that file: an addition means re-reading the whole document and
  leaving it consistent, not appending. Flag every other passage that would need to change.

## Deliver

`notes/budget-tiers-proposal.md`, containing:

- The tier scheme, with each tier's name, budget, and the situation it maps to.
- The exact prompt wording you propose, quoted as a block, ready to drop in — and for each
  block, which file and which existing passage it replaces or joins.
- The anti-gaming reasoning, honestly stated, including what you expect to fail.
- The proposed DESIGN-TRUTH passage, marked as Andrew's to paste.
- Worked examples: take at least three real bad bullets from the brief's transcript and
  rewrite them under your scheme, showing the tier chosen and the word count. This is the
  part Andrew will judge it on — if the rewrites don't visibly read better at half-pane
  width, the scheme is wrong.

Write for a reader who will skim. The proposal is itself human-facing output and will be
judged as an example of what it argues for.

Commit the note on the current branch. Then `sb done` with a plain-language two-line
summary. Do not block for a human — your parent is handling that.
