# Hostile read of the three rewrites in `notes/block-message-bloat.md`

Read as Andrew would: cold, in a terminal, four other threads open, wanting to
answer in one word. Source read: `git show researcher-35:notes/block-message-bloat.md`
(458 lines, whole file — originals, markup, rewrites, and the two summary sections).

**Verdict up front:** Ex 1 — mine, narrowly. Ex 2 — mine, decisively; theirs is
not merely shorter, it is wrong. Ex 3 — theirs, near enough that my change is
one deleted quote block.

The headline finding is not about any of the three individually: **character
count is a proxy that can be gamed.** The rewrite that cut the most (ex 2, 66%)
is the only one that changed what Andrew would be agreeing to. Cutting is a
lossy operation and nobody in the note checked the output against the input for
meaning, only for size.

---

## Example 1 — spec self-contradiction

### 1. Time-to-decision

The message announces *that* a decision exists in line 2 ("One thing left needs
your call"), but *what* the decision is only lands at "Which do you want?", which
is line 12 of 20 in a narrow pane. So 55–60% of the vertical space is above the
ask.

That is not automatically a tax here — the two paragraphs in between are the
decision. But it means the shape is "read everything, then choose", which is
precisely the "I feel like I need to read every single word" complaint. Nothing
in the message tells him he *can* stop at the options and skim upward only if an
option surprises him.

### 2. What can still go

- **The doubled instruction.** `"Which do you want? (1 recommended.)"` at the top
  of the list and `"Reply with a number."` at the bottom say the same thing
  twice, 6 lines apart. One goes. The trailing one is the weaker of the two —
  it arrives after he has already decided.
- `"so that assertion is false by definition and would crash every sb command
  at import"` — "false by definition" is the reader's own arithmetic on the two
  numbers already given. `60 >= 287 is false, so it would crash every sb command
  at import` says it with the numbers doing the work.
- `"Turns out"` — filler. `"My task paraphrased it onto the wrong constant."` —
  the previous sentence already established the doc means a different constant;
  this sentence restates that as a diagnosis of the agent's own error, which is
  the agent's problem, not Andrew's decision input.
- **Option 3 is a dead option presented as a live one.** Its own text says the
  doc "explicitly rejects this scale" and that it makes a dead agent read
  "working" for 9.5 minutes. Nobody picks it. The note's own recurring-pattern
  list ranks "asking a question and then answering it yourself" as cost #2 and
  catches it in ex 2's Q3 — and then the ex 1 rewrite does it and it goes
  unmarked. It survives only if it costs one line, which it doesn't here (3).

### 3. What was cut that should NOT have been

This is where the ex 1 rewrite loses more than it gains.

- **`"(liveness debounce)"`.** The note calls this "a gloss on the stage name
  Andrew already knows" with "zero decision value" and deletes it. Under Andrew's
  own clarification — one sentence of reorientation is *wanted* — this two-word
  parenthetical is the entire reorientation in the message. `"Stage 4a is done"`
  is meaningless to a reader holding four other threads; `"Stage 4a (liveness
  debounce) is done"` is not. This is the cheapest sentence-fragment in the file
  and it was the first thing cut.
- **Who says 60s.** The original: `"both the task and design/fix-options.md say
  the new confirm window should be ~60s"`. The rewrite: `"the confirm window is
  meant to be ~60s"` — passive, sourceless. The entire message is "the spec
  contradicts itself"; *which* spec says what is the crux of the contradiction.
  Removing the attribution invites exactly one follow-up: "meant by whom?"
- **`"(fix-options.md ~L1565-1572)"`.** The note classes inline citations as
  "evidence-for-the-record, not decision input". For most messages that is right.
  Here the decision turns on *what a document actually says*, and Andrew is being
  asked to overrule his own doc's paraphrase. A file:line is the cheapest possible
  way for him to check the claim without a round trip. ~30 characters saved
  against one plausible follow-up question is a bad trade.
- **`"it is broker's constant"`** (from option 1). The note reads the whole clause
  as file-scoping, and the file list genuinely is scoping. But the *ownership*
  half is blast radius: option 1 changes the behaviour of a constant belonging to
  a subsystem the task never mentioned. The rewrite keeps the behavioural cost
  ("sb ask waits ~5min") and drops the fact that this is someone else's
  subsystem. Borderline, but blast radius is decision input in a way that
  "which files I'll touch" is not.

### 4. Shape

The options are **not parallel and therefore not comparable.**

- Opt 1: assertion + settings change + "Fixes the real bug" + "Cost: ..."
- Opt 2: assertion + a parenthetical justification + a comparison to the task's
  wording (not a cost)
- Opt 3: change + doc's objection + a cost

Three different internal shapes, so the eye cannot travel down the same column
to compare. Every option needs re-parsing from scratch. Within each option the
what and the cost run on in the same wrapped paragraph.

### 5. Answerability

Yes — one number. This is the rewrite's clear win over the original and it is
preserved.

### My version

```
Stage 4a (liveness debounce) is done; one assertion left, and the spec
contradicts itself.

My task says: assert confirm-window >= SPAWN_GRACE. That is 60 >= 287 —
false, so it would crash every sb command at import.

fix-options.md L1565 turns out to describe a different constant: broker's
gone_grace (60s). That one is a real bug today — sb ask gives up on agents
that are still spawning.

Pick a number (1 recommended):

1. Fix the real bug: gone_grace -> 287s, assert against it.
   Cost: sb ask takes 5min to declare a target gone. broker's constant, not mine.

2. Flip my assertion: confirm-window <= SPAWN_GRACE.
   Cost: opposite direction to my task's literal wording.

3. Confirm-window -> 287s, assert exactly as worded.
   Cost: a dead agent reads "working" for 9.5min; fix-options.md rejects this scale.
```

Same information, one fewer instruction line, citation and reorientation
restored, and every option is two lines with the same two slots: **what changes**
on line one, **what it costs** on line two. He can read the three cost lines
alone and decide. Option 3 stays but is visibly dead from its cost line, which is
cheaper than arguing it in prose.

### Which wins

**Mine, narrowly.** Theirs is a good cut. The deciding difference is the parallel
option shape — it lets him decide from three lines instead of nine — plus the
restored `(liveness debounce)` and the doc citation, both of which were cut on a
rule ("no status, no citations") that misfires on this particular message.

---

## Example 2 — DESIGN-TRUTH conflict

### 1. Time-to-decision

The bold header names the problem on line 1. Good — best of the three on this
axis in principle. In practice the header is one sentence doing three jobs
(what happens / that it matches :279 / that it broke this task) and wraps to 3–4
physical lines, so the very top of the message is a wall. The actual ask is at
item 1, roughly line 10 of 16.

### 2. What can still go

- **The call chain.** `"Fork path: Broker.delegate -> _fork_for ->
  _attach_workspace (broker.py:2748), defaulting to BASE_BRANCH=origin/main."`
  Three function names to decide a policy question. One file:line carries the
  same verifiability. The chain is engineer-to-engineer evidence in a message
  addressed to the person deciding policy.
- **Item 2 is ex 2's Question 3 all over again.** `"Parent's checkout is dirty
  (the usual case) — child can't inherit uncommitted work. Recommended: fork
  from the committed tip and tell the parent."` There is exactly one live answer:
  you cannot `git worktree add` a working tree, and refusing dirty spawns would
  refuse nearly all of them. The note caught the fake question at Q3 and shipped
  another one at item 2. A determined consequence is not a decision; state it
  and offer him the veto.

### 3. What was cut that should NOT have been

**This is the serious one, and it is not an omission — it is a corruption.**

Original Q1 recommendation, in full: *"yes, narrowed rather than replaced. Under
this rule a top orchestrator standing on `main` still gets `origin/main` ... Only
a parent sitting on a feature branch changes: its children fork from that
branch's tip."*

The narrowing axis is **which branch the parent is on** (main vs. a feature
branch).

Rewritten Q1: *"Recommended: yes, narrowed — only when the parent has its own
worktree."*

The narrowing axis is now **whether the parent has a worktree.** Different rule.
And by the message's own facts bullet — *"every child of an agent with no
worktree — i.e. every child of a top orchestrator — starts at `origin/main`"* —
the reported bug is precisely a parent with **no** worktree (a top orchestrator
in Andrew's checkout, sitting on `fix-sb-path`). The rewritten recommendation
carves that case out. Andrew says "yes", the agent implements exactly what he
approved, and the bug that prompted the whole task survives.

That is the failure mode the task asked me to hunt for, in its worst form: not a
cut that provokes a follow-up question, but a cut that gets a confident wrong
"yes".

Second, smaller:

- **The text of :279 itself.** The rewrite says "matches DESIGN-TRUTH:279" and
  never quotes it. The original quoted it: *"A workspace forks from `origin/main`
  by default."* The decision is literally whether to amend that sentence. Making
  him open the file to see the sentence he is being asked to overrule, to save
  ~50 characters, is the trade backwards. Cutting the *second* citation
  (`:34-36`) was right; cutting the first was not.

Cuts I agree with and would keep cut: the opening throat-clearing, "(facts, not
proposals)", "That is the finding in the brief, reproduced", the justify-the-block
paragraph, "as the brief describes", and Q3 in full.

### 4. Shape

- A 3–4 line wrapped bold header is a wall at the position where scanning starts.
  Bold plus long is the worst combination — it demands attention and then makes
  you work.
- Item 1 fuses question and recommendation into one paragraph, so there is no
  typographic seam between "the thing to answer" and "what I think". Same defect
  the note diagnoses in the *originals*, carried into the rewrite.
- Items 1 and 2 are not grammatically parallel: 1 is a question, 2 is a statement
  with a recommendation attached. The eye expects two questions and finds one.

### 5. Answerability

**No, not cleanly.** The close says "Say yes and I'll implement" but there are two
numbered items and item 2 is not a question, so "yes" has no well-formed referent
for it. He has to write "yes to both" and trust the mapping. Collapsing item 2
into a stated default makes the whole message a genuine one-word `yes`.

### My version

```
Delegated children always fork origin/main, never the parent's branch. That is
DESIGN-TRUTH:279 — "A workspace forks from origin/main by default" — and it is
what broke this task: this worktree started at origin/main, missing all 17
commits on my parent's branch fix-sb-path. (broker.py:2748)

One question:

Does :279 yield to "a delegated child forks from whatever branch its parent's
checkout is on"?

  Recommended: yes. A parent on main still gets origin/main, exactly as today.
  Only a parent on a feature branch changes.

Unless you say otherwise: a dirty parent tree forks from the committed tip and
the parent is told — you cannot git worktree add a working tree.
```

One question, one word answers it, and the recommendation sits on its own
indented lines so the seam between "what I'm asking" and "what I think" is
visible without reading either. The dirty-tree consequence is stated as a default
he can veto rather than posed as a decision he must make. The rule quoted back is
the original's rule, not a narrower one.

### Which wins

**Mine, decisively.** Not on shape — on correctness. Theirs asks him to approve a
rule that would not fix the bug the message is about. Everything else here is
secondary to that.

---

## Example 3 — role-permission refusal

### 1. Time-to-decision

Two lines. Best of the three by a distance, and roughly the ceiling for this
kind of message. No tax worth quantifying.

### 2. What can still go

- **The block quote.** The prose already says `"worker role can't delegate
  (rights are orchestrator-only)"`. The quote beneath it says the same thing in
  the tool's words, then trails off in `"..."`. The elision is the tell: the
  half that got cut (*"say so to your parent with sb done rather than growing a
  tree under yourself"*) was the only part the paraphrase didn't already carry.
  Keeping a truncated quote of a sentence you just paraphrased costs two lines
  and a visual mode-switch for zero new information. The rewrite fixed the
  original's redundancy in one direction (dropped `"So this is a role-permission
  refusal, not a crash"`) and left it standing in the other.

Nothing else here is fat. This is close to as short as the message can be while
still being answerable.

### 3. What was cut that should NOT have been

Essentially nothing — the strongest of the three cuts. Two marginal notes:

- `"I am role worker"` is gone; it is inferable from "worker role can't delegate"
  plus the fact that the agent ran the command. Fine.
- The message no longer states plainly that nothing was spawned. The note calls
  `"I did nothing else and spawned nothing"` a question nobody would ask. For a
  message about tree structure I think it *is* asked, but option 1 ("want lead to
  run it instead") implies it clearly enough. I would not restore it.

### 4. Shape

Good. Short lines, two visually parallel options, one recommendation, no
scrolling. Dropping the quote block removes the only mode-switch left.

### 5. Answerability

Yes — "1" or "2", and "2" is a clean no-op. Correct.

### My version

```
Ran the sb delegate you sent, verbatim. It refused (exit 1): a worker role has
no delegate rights — orchestrator only. Nothing was spawned.

1. Have mpq7k-lead (the orchestrator) run it instead? Recommended: yes, same
   grandchild.
2. Or was the refusal itself what you were testing? Then I close out.
```

### Which wins

**Theirs, near enough.** My only substantive change is deleting the truncated
quote and folding "nothing was spawned" back in. That is a nit-level difference,
not a verdict-level one. If ex 3 were the only example, the note's method would
look fully vindicated.

---

## What the three, taken together, say about the method

The note's recurring-patterns list is largely right, and ex 3 shows what happens
when it is applied to a message with no hard content. The failures cluster where
the rules meet a decision with real technical substance.

1. **Rules stated as categories misfire on individual messages.** "Citations are
   evidence-for-the-record", "status doesn't feed the decision", "restating the
   task is throat-clearing" are all true on average and all wrong at least once
   here: the doc citation in ex 1 *is* how he checks the claim; `(liveness
   debounce)` *is* his reorientation; the :279 quote *is* the thing being
   amended. The usable distinction is not a category of text but a question
   asked of each span: **does this change which option he picks, or does it let
   him check the one that does?** Everything else goes.

2. **Compression that rewrites a recommendation is a different operation from
   cutting.** Ex 2's rewrite paraphrased a rule into a narrower one. Nothing in
   the note's method looks for this, because the method measures characters
   before and after. Any process that shortens must diff meaning too, not size.

3. **"Question with one live answer" is under-applied.** The note ranks it #2 and
   catches ex 2's Q3, then ships ex 2's item 2 and ex 1's option 3 — both
   unpickable, both formatted as live choices. A choice that costs the reader a
   full read-parse-decide cycle and has one answer is worse per character than
   almost anything on the cut list.

4. **The seam matters more than the length.** Andrew's complaint names wrapping,
   spacing, and walls before it names words. Ex 2's rewrite is 66% shorter and
   opens with a 4-line bold wall; ex 1's rewrite is only 44% shorter and reads
   fine. What fixed my versions was not deleting more, it was giving every
   option the same two slots and putting a break between the ask and the opinion,
   so the skippable half is visibly skippable.

5. **One-word answerability is a design constraint, not an outcome.** Ex 2 fails
   it only because a determined consequence was left in question form. Asking
   "can he answer this with one token?" before sending would have caught it.

None of this points at a template, a section list, or a word budget — the four
findings above are all tests you run against a message you have already written.

---

## Caveman mode — how far telegraphic register can go before it costs precision

Extra scope from Andrew via main-16: he reads faster in telegraphic register
(articles and filler dropped — *"spec contradicts itself. two options. pick
one."*), and wants it **partially** applied, ~10–25%, not the whole message in
grunt-speak. Below: example 1 at both doses, then the failure point.

Example 1 is the right one to test on — it is the message with the most
irreducible technical content, so it is where telegraphic register will break
first if it breaks at all.

### ~10% caveman — scaffolding and option labels only

Only the connective/organisational text goes telegraphic. Every sentence that
carries a technical claim stays full prose.

```
Stage 4a (liveness debounce) done. One assertion left. Spec contradicts itself.

My task says: assert confirm-window >= SPAWN_GRACE. That is 60 >= 287 —
false, so it would crash every sb command at import.

fix-options.md L1565 turns out to describe a different constant: broker's
gone_grace (60s). That one is a real bug today — sb ask gives up on agents
that are still spawning.

Pick a number. 1 recommended.

1. Fix the real bug: raise gone_grace from 60 to 287s, assert against it.
   Cost: sb ask waits 5 min before declaring a target gone. broker's constant.

2. Flip my assertion: confirm-window <= SPAWN_GRACE.
   Cost: opposite direction to my task's literal wording.

3. Raise confirm-window to 287s, assert exactly as worded.
   Cost: a dead agent reads "working" for 9.5 min. fix-options.md rejects this scale.
```

Changed from my full-prose version: the opening run-on became four short
sentences; "Pick a number (1 recommended):" became two; two option-cost lines
lost a joining clause. Nothing technical moved. Roughly 8 words gone out of
~150 — and the visible effect is larger than the word count, because the
opening line now breaks into four stops instead of wrapping as one.

### ~25% caveman — most connective tissue gone

```
Stage 4a (liveness debounce) done. One assertion left. Spec contradicts itself.

Task says: assert confirm-window >= SPAWN_GRACE. That is 60 >= 287. False.
Asserting it crashes every sb command at import.

fix-options.md L1565 actually describes a different constant — broker's
gone_grace, 60s. Real bug today: sb ask gives up on agents still spawning.

Pick a number. 1 recommended.

1. Fix real bug. gone_grace: 60 -> 287s. Assert against it.
   Cost: sb ask waits 5 min before declaring a target gone. broker's constant.

2. Flip my assertion. confirm-window <= SPAWN_GRACE.
   Cost: opposite direction to my task's wording.

3. Confirm-window -> 287s. Assert as worded.
   Cost: dead agent reads "working" 9.5 min. fix-options.md rejects this scale.
```

Still intact: every number, every constant name, the direction of every
comparison, and both prepositions that carry a relation (`from 60 to 287s`
survives as the arrow `60 -> 287s`; `waits 5 min **before** declaring` survives
in full).

### Where it breaks — the same lines, one step further

This is the dose past 25%. Each pair is *the sentence above*, with one more
word dropped, and what it now also means.

**1. A range that loses its endpoints.**

- 25%: `gone_grace: 60 -> 287s`
- Too far: `raise gone_grace 287s`
- Now reads as either **to** 287 or **by** 287 (i.e. 347s). Same characters,
  two different systems. `->` between two numbers is safe; a bare number after
  a verb is not.

**2. A duration that loses its preposition.**

- 25%: `Cost: sb ask waits 5 min before declaring a target gone.`
- Too far: `Cost: sb ask waits 5 min declaring target gone.`
- Now reads as either "waits 5 min, *then* declares" (correct — the cost is
  latency) or "spends 5 min *in the act of* declaring" (a slow operation, a
  different and much worse-sounding defect). `before` is one word and it is the
  entire meaning of the option's cost.

**3. A fork that loses its direction** — from example 2, the sharpest case:

- Full: `a delegated child forks from the branch its parent's checkout is on`
- Too far: `child forks parent branch`
- Three readings now. (a) forks **from** the parent's branch — intended.
  (b) forks the parent's branch — i.e. creates a copy of it, a different
  operation. (c) "the parent branch" as a noun phrase meaning `main`, which is
  the exact status quo the message is asking to change. A reader who takes (c)
  answers "yes" to a no-op.

The rule that falls out, and it is mechanical enough to apply while writing:
**drop articles, copulas and hedges; never drop a preposition or a comparative.**
"the", "is", "just", "actually", "which" carry no relation and cost nothing.
"from", "to", "before", "against", "by", ">=", "->" *are* the relation — in a
message about ordering constants and forking branches, they are the payload.
Telegraphic register is free on scaffolding because scaffolding has no relations
in it; that is why 10–25% works and 40% does not.

### Which register I would ship

**~10%, and only on the scaffolding.** Reasons, in order:

1. The measured gain is almost entirely in the opening and the option labels,
   and those are exactly the spans with no relational content. That is where
   telegraphic is free.
2. The technical paragraphs are the ones he says he must read every word of.
   Making them terser does not make them faster — a dropped `before` costs him a
   re-read, which is more expensive than the two characters saved.
3. 25% is defensible and I would not object to it, but its extra savings come
   from sentences like `That is 60 >= 287. False.` where the gain is one word
   and the risk is that the next writer, imitating the register, applies it one
   step further to a line that does carry a preposition. 10% has no such
   gradient to slide down.

The honest summary: register is a smaller lever than shape. Going from the
original ex 1 to my full-prose version saved more of his time than going from my
version to the 25% one — parallel options and a visible seam between ask and
opinion do more than dropping "the".

---

*Written by reviewer-19. Committed on branch `reviewer-19` at
`notes/rewrite-critique.md` in the reviewer-19 worktree.*
