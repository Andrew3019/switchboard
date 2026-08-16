# Task: land the approved prompt edits

This is IMPLEMENTATION. Andrew has approved all of it, including editing
`DESIGN-TRUTH.md` — normally his file only. He said: "approved this. approved u to edit
design truth with my intent as well." Write that file in his voice and to his intent,
conservatively.

You own every file you touch. No other agent is editing prompt files right now.

## Read first, in order

1. `/Users/andrew/Code/switchboard/notes/agent-handoff-wording-brief.md` — his original
   complaint, with the real transcript he annotated.
2. `notes/budget-tiers-proposal.md` — the approved readability wording (v2, simplified).
   Ignore its title; the tier scheme was thrown out and this is the plain version.
3. `notes/handoff-wording-proposal.md` — the approved handoff wording, with one change
   below.
4. `notes/readability-prompt-diagnosis.md` and `notes/handoff-prompt-diagnosis.md` — the
   background, if you need it.

## Three pieces of work

### 1. The readability edits — apply as proposed

From `notes/budget-tiers-proposal.md`:

- The `defaults/protocol.md` replacement for lines 244-256. Three added sentences (length
  aim, one idea per bullet, don't cram a line) plus the two-word fix to the closing
  sentence so it stops saying "no length to hit".
- The `DESIGN-TRUTH.md` replacement passage at 225-228, plus both flagged knock-on edits
  (the bullets/lists paragraph at 181-184, and the header change).

Apply as written. Andrew approved this text. Do not improve it, do not re-argue it, do not
add to it. If you find something actually wrong — a line number that has moved, a sentence
that no longer parses in context — fix the mechanical problem and say so in your summary.

### 2. The handoff wording — apply with one change

From `notes/handoff-wording-proposal.md`, but **do not put the same paragraph in three
files**. The proposal repeats near-identical wording in `protocol.md`, `dispatcher.md`, and
`lead.md`. That is three copies to keep in sync.

Instead:

- **Define it once, fully, in `defaults/protocol.md`** — every role reads that file, which
  is what stops the rule going missing from one role the way it did for `dispatcher`.
- In `defaults/roles/dispatcher.md:233-240` and `defaults/roles/lead.md:236-238`, keep the
  existing paragraph's own job and add **one short clause** pointing at the shared rule.
  Enough that a dispatcher reading only its own file knows the handoff exists and when it
  fires. Not a restatement of the mechanics.
- `dispatcher.md`'s existing "When a child reports done..." must become "**The first time**
  a child reports done..." — that single word carries the discriminator and must not be
  lost.

Andrew asked for the rule to be stated generally rather than as a procedure. This is the
rule, in his lead's words, and the shared definition should read as this plus its mechanics:

> **You may report a child's work once. You may not become the channel for the
> conversation about it.**

The discriminator stays as proposed — "has this child's finished work already reached the
person once?" — because it is one question, not a scheme.

Also apply the proposal's `DESIGN-TRUTH.md` work: the new principle entry next to the
"When work finishes" entry, and the disambiguating clause on line 258 ("a dispatcher
relays; it does not interpret" uses "relay" in the opposite direction and will read as a
contradiction if left alone).

### 3. NEW — the "Where we are now" line before blocking

Andrew added this after approving the rest. His words:

> "before sb block, there still needs to be a one line (excluding section header) 'Where
> we are now' that summaries 1. overall task/topic; 2. where we are in this topic (e.g.
> investigating design, etc.). 20 words max total excluding header."

Spec:

- A section headed **Where we are now**.
- One line under it. Twenty words maximum, not counting the header.
- It says what the overall task or topic is, and what stage that topic is at — investigating,
  designing, waiting on a decision, implementing, verifying.
- It goes in the chat message that precedes `sb block`. Place it at the **end** of the
  message, immediately before blocking, since that is where he asked for it.

Where to write this rule: in `defaults/protocol.md`, in the `sb block` mechanics — the part
that already says the real message goes in your own chat and the block reason goes on the
board. Every role inherits it from there. Do not copy it into role files.

**One thing to resolve:** `protocol.md` already says "Open with one line restating what you
were asked, always." That is close to, but not the same as, the new line — one is what was
asked, the other is where the work stands. Keep both, and make the two sentences read as
distinct jobs rather than a near-duplicate. If in context they genuinely collide, say so in
your summary rather than dropping either.

Write an example into nothing — no worked example in the prompt text. Andrew's standing
rule on `DESIGN-TRUTH.md` is that a copyable example becomes a mould.

## Constraints

- Prompt text is agent-facing prose. Match the surrounding register exactly — these files
  have a distinctive voice and an edit that reads like a different author is a defect.
- `DESIGN-TRUTH.md`: the standing rule is that any addition means re-reading the whole
  document and leaving it consistent, not appending. Do that. Entries there carry a
  confirmation date — use `confirmed 2026-08-16` for the ones Andrew has approved.
- Check whether any role file carries its own echo of the old "no length limit" language,
  or its own copy of the block instructions that now needs the "Where we are now" line.
  Grep for it; the earlier diagnosis flagged this as unchecked.
- Run the test suite: `python -m pytest tests` (on this machine use
  `/Users/andrew/anaconda3/bin/python`). Some tests may assert on prompt text. Fix
  genuine breakage caused by your edit; do not weaken a test to make it pass.
- Do not push, do not open a pull request, do not touch `main`. Commit on the current
  branch only.

## Deliver

Commit the edits. Then `sb done` with a plain two-line summary: what landed, and anything
you had to decide or could not do. Do not block for a human — your parent handles that.
