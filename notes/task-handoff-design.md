# Task: design the wording that stops agents relaying between the human and their children (proposal only)

PROPOSAL ONLY. Do not edit any prompt file, any role file, `defaults/protocol.md`,
`defaults/prompts.toml`, or `DESIGN-TRUTH.md`. Your entire output is one new note.

Another agent is designing the *readability* wording in parallel and owns
`notes/budget-tiers-proposal.md`. Stay out of that file and out of that topic.

## Background — read these first, in order

1. `/Users/andrew/Code/switchboard/notes/agent-handoff-wording-brief.md` — Andrew's
   complaint verbatim. The second half, from "followups are not good", is your subject.
2. `notes/handoff-prompt-diagnosis.md` — the diagnosis already done. Do not redo it. It
   confirms the code already supports the flow Andrew wants; this is purely wording.
3. `DESIGN-TRUTH.md` — for how principles are stated there, and to find where this one
   would live.
4. `defaults/roles/dispatcher.md` and `defaults/roles/lead.md` — the two files at issue.

## The behaviour Andrew wants

A dispatcher had finished a run and blocked with two leftover questions. Andrew asked for
more context on both. The dispatcher restored the two children that held the detail, asked
them, waited, and **relayed their answers back in its own words**. Andrew still couldn't
decide, because the relayed version was second-hand and thin.

What he wanted instead:

- Dispatcher restores the two agents.
- Dispatcher tells each to explain its own thing, and to `sb block` so Andrew reads it
  directly.
- Dispatcher then calls `sb done` on itself and gets out of the way.
- Andrew talks to those two agents directly, in their own panes, back and forth.
- When he's done with them, they `sb done` back up to their parent.

His words: *"the dispatcher should avoid piping outputs between me and agents. this should
be a design truth or principle somewhere."*

## What the diagnosis found (do not re-derive, build on it)

1. `defaults/roles/dispatcher.md:233-240` is a **positive instruction to relay** — when a
   child reports done, the dispatcher writes what the child said and blocks. It is the only
   path in the file. It exists for a real reason: it was written to stop a dispatcher
   silently sitting on a finished report that reached nobody. Your wording must not
   reintroduce that failure.
2. The rule Andrew wants already exists at `defaults/roles/lead.md:236-238` — "don't become
   a permanent proxy, name that child and point them at it" — but it is scoped to `lead`
   only. The dispatcher never got a copy.
3. **No prompt anywhere** says a parent may instruct a child to `sb block` for the human.
   Blocking is described everywhere in the first person, as something an agent does for
   itself. The move Andrew wants has no name in any prompt.

## What to design

### 1. The branch inside the dispatcher's report rule

`dispatcher.md:233-240` needs a second path without losing its first. Design the
discriminator:

- When is "I relay a short pointer and block" still correct? (A simple finished report
  probably is — Andrew should not have to go talk to five agents to learn five things
  landed.)
- When does the exchange instead belong directly with the child? Candidate signals: the
  human is asking a follow-up question rather than receiving a result; the answer is
  contestable; a decision depends on detail the parent doesn't hold; the thread is clearly
  going to take more than one turn.
- Write it so an agent can tell which case it is *before* it starts writing, not after.

### 2. Name the handoff move

Give the pattern a plain name and describe the verb sequence explicitly: restore if needed
→ `sb tell` the child what to explain and instruct it to `sb block` → parent calls `sb done`.

- Say plainly that a parent may instruct a child to block, and that this is normal — it is
  currently unimaginable from the prompt text alone.
- Say what the parent tells the child, so the child's block message is actually useful:
  it must know what specifically to explain and who it is writing for.
- Cover the parent's own exit: it says, in one line, who Andrew should now talk to and about
  what — then finishes. It does not wait.
- Confirm against `switchboard/broker.py` that each step you describe works as written. The
  diagnosis says it does; spot-check rather than trust it, and say what you checked.

### 3. Where the principle lives

Andrew asked for this to be a design truth or principle. Decide and argue:

- Does it belong in `DESIGN-TRUTH.md` as a principle, in `defaults/protocol.md` as a rule
  every role sees, in both role files, or some combination?
- The diagnosis notes the rule existing in exactly one of two structurally parallel role
  files is what caused this. Whatever you propose should be robust to that recurring — i.e.
  prefer a home where it cannot be missed by the next role that needs it.
- `DESIGN-TRUTH.md` is **Andrew's file only**. Any text for it is a proposal for him to
  paste, clearly marked, and must leave the whole document consistent rather than being
  appended. Flag any other passage it affects — including `DESIGN-TRUTH.md:258` ("a
  dispatcher relays; it does not interpret"), which uses "relay" in a different sense and
  will read as a contradiction if left alone.

### 4. The second-order failure

Even under its existing weaker rule — "its words, not a summary you invented" — the
dispatcher in the transcript wrote entirely its own analytical prose. Consider whether your
wording needs anything that makes that harder, or whether the handoff branch makes the
question moot.

## Deliver

`notes/handoff-wording-proposal.md`, containing:

- The exact wording you propose, quoted as blocks, each labelled with the file and the
  existing passage it replaces or joins.
- The discriminator for relay-vs-hand-off, stated so it can be applied without deliberation.
- The proposed DESIGN-TRUTH passage, marked as Andrew's to paste, plus every knock-on edit.
- A walk-through of Andrew's actual transcript under your wording: what the dispatcher would
  have done at each step instead, in order.

Write for a reader who will skim: short bullets, plain words, no internal jargon. Andrew
reads at half screen width and is judging us on exactly this.

Commit the note on the current branch. Then `sb done` with a plain-language two-line
summary. Do not block for a human — your parent is handling that.
