# Task: redo the length-budget proposal, much simpler (proposal only)

PROPOSAL ONLY. Do not edit any prompt file, role file, `defaults/protocol.md`,
`defaults/prompts.toml`, or `DESIGN-TRUTH.md`. Your output is one rewritten note.

## Read first, in order

1. `/Users/andrew/Code/switchboard/notes/agent-handoff-wording-brief.md` — Andrew's
   original complaint, with real transcript excerpts he annotated.
2. `notes/readability-prompt-diagnosis.md` — the diagnosis. Still valid, don't redo it.
3. `notes/budget-tiers-proposal.md` — **the proposal you are replacing.** It is
   over-engineered. Read it to know what to cut, not what to keep.
4. `defaults/protocol.md`, human-facing output paragraph (~lines 240-260).
5. `DESIGN-TRUTH.md`, human-facing output section (~lines 180-230).

## What happened

Andrew approved adding a length budget. He asked for "some dynamicness" — his own manual
prompting says "max 15 words each, sometimes 10, sometimes 20, depends how complex".

The previous proposal turned that into a three-tier scheme (S/M/L) keyed to counting the
independent falsifiable claims in each bullet, with a table, a default tier, a
split-before-you-use-L rule, and a per-bullet-not-per-message argument.

Andrew's verdict, verbatim:

> "even this is a little too complex for something as simple as the agent's output tone.
> dumb this down a little, dont causing over anchoring or regression with these
> restrictions. what 'general' changes are we making. e.g. fixed word counts and line
> counts based on 'abstract' and 'arbitrary' complexity levels. etc. redo this"

Read that carefully. Three separate objections:

- **Too complex for what it is.** This is output tone. It does not warrant a taxonomy.
- **Over-anchoring / regression.** A rigid scheme makes an agent spend its attention
  counting claims and picking labels instead of writing well. The output gets stilted and
  uniform — worse than what we have, in a new way.
- **The tiers are abstract and arbitrary.** "Independent falsifiable claims" is invented
  machinery. So are the labels S/M/L. He is calling out that the complexity levels are
  made up and the numbers hanging off them are made up.

## What to produce instead

**General guidance an agent absorbs, not a procedure it executes.** The test: could a
competent writer read it once and just write better, without stopping to classify
anything? If any part requires the agent to categorise its output before writing, cut it.

Concretely:

- Keep a sense of length — Andrew does want short bullets and he did give real numbers.
  But express it the way he does when prompting by hand: a rough aim, stated once, plainly.
  Not a table, not named tiers, not a lookup.
- Say the "depends on complexity" part in ordinary words that an agent already understands
  without a definition. It should read as a normal instruction from a person, not a rule
  with a schema.
- Keep the few rules from the old proposal that are genuinely simple and were his own
  complaints — one idea per bullet, prefer cutting detail, don't cram many items onto one
  line. State each in one sentence. Do not build them out.
- Cut everything else. The tier table, claim counting, the default-tier rule, the
  split-before-L rule, the per-bullet-vs-per-message argument, the anti-gaming section as
  a section. If an anti-gaming point survives it should be one clause inside a sentence.

Be aggressive. A good outcome here is noticeably shorter than the proposal it replaces.
If you find yourself writing a heading for a sub-rule, that sub-rule probably shouldn't
exist.

## Also check

`notes/handoff-wording-proposal.md` (a sibling agent's, on a different topic — the
dispatcher relaying between Andrew and its children). Andrew did not criticise it, but he
was reacting to a message that summarised both. Read it with the same lens and say, in a
short section at the end of your note, whether any part of it has the same over-machinery
smell and should be simplified too. Do not rewrite it — just flag, specifically.

## Deliver

Rewrite `notes/budget-tiers-proposal.md` in place (same path — it is superseded, not
supplemented). It should contain:

- The proposed wording, quoted as a block, ready to drop in — with the file and the
  existing passage it replaces.
- The `DESIGN-TRUTH.md` passage, marked clearly as Andrew's to paste, plus any knock-on
  edits. Note the existing passage there forbids exactly this ("no word or line limit") and
  gives a reason — the new text must deal with that reason honestly and briefly. Briefly.
- Worked rewrites of the same real bad bullets from the brief, so the effect is visible.
- Your flag on the handoff proposal.

Write it short and plain. The note is itself an example of what it argues for, and Andrew
reads at half screen width.

Commit on the current branch. Then `sb done` with a plain-language two-line summary. Do
not block for a human — your parent handles that.
