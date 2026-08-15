# Bloat in real pre-`sb block` messages (happy-path examples only)

Task: Andrew looked at examples of the "happy path" pre-`sb block` message (the
ones that DID follow the numbered-questions-with-recommendations format, the
ones a prior researcher called *good*) and said even those are too long — too
many words that don't bear on the decision, too much wall-of-text, not enough
spacing. This note goes back to the full raw transcripts (not the excerpts
from `researcher-34`'s writeup) for three of those happy-path examples, marks
up concretely what's deletable, and rewrites each at the length it should have
been.

Source transcripts (full paths, so this is checkable):
- Ex 1: `~/.claude/projects/-Users-andrew--herdr-worktrees-switchboard-teardown-fix/9385c52f-f0c5-4d23-9fbb-d2449a42dcea.jsonl`, event index 236. Unusually, this agent put its entire message *inside* the `sb block "..."` argument itself rather than as chat text before the call — so what's below is the literal command string, not a preceding assistant turn.
- Ex 2: `~/.claude/projects/-Users-andrew--herdr-worktrees-switchboard-fix-fork-branch/7c12a25c-dbaa-44a8-bccc-d098c8e1fe93.jsonl`, the assistant turn immediately before the `sb block "need a decision: forking children..."` tool call.
- Ex 3: `~/.claude/projects/-Users-andrew--herdr-worktrees-live-mpq7k-kid/1c72c573-05e0-48a7-a925-7d62683b5f01.jsonl`, the assistant turn immediately before `sb block "delegate refused: worker role lacks delegate rights"`.

---

## Example 1 — `teardown-fix`, spec self-contradiction (1924 chars → 1071)

Full original text, with the deletable spans **struck through in description**
(quoted verbatim below, markup follows):

> Stage 4a (liveness debounce) is built and committed as 25a777e — absent_since
> column, GONE_CONFIRM_GRACE=60s, both writes in the reap path, tests green
> (1467 passed). One piece left, and it needs your call because the spec
> contradicts itself.
>
> My task says: add a load-time assertion that the gone-confirmation window is
> never shorter than the spawn-detection window. The numbers: SPAWN_GRACE =
> 287s, and both the task and design/fix-options.md say the new confirm window
> should be ~60s. So '60 >= 287' is false — asserting it at import kills every
> sb command, including the sb done a fleet needs to drain.
>
> Reading the doc itself (fix-options.md ~L1565-1572, and the design map), the
> assertion it describes is actually about a DIFFERENT constant: ask()'s
> gone_grace (timeouts.gone_grace = 60.0, used by broker.ask to give up on a
> vanished target). That one is a real bug today — 60 < 287 means sb ask
> abandons a target that is merely still spawning. My task paraphrased it onto
> my new window.
>
> Which do you want? (1 is my recommendation.)
>
> 1. Assert timeouts.gone_grace >= SPAWN_GRACE at load, and raise gone_grace
>    from 60 to >= 287 in defaults/settings.toml so it holds. Matches the
>    doc's own words and fixes the real bug. Cost: sb ask waits ~5 min before
>    declaring a target vanished, and it is broker's constant (I would not
>    touch broker.py — only settings.toml and an assertion in status.py).
> 2. Keep my window at 60s and assert the direction that is satisfiable:
>    GONE_CONFIRM_GRACE <= SPAWN_GRACE (the confirm window is a debounce, not
>    a second spawn grace). Opposite direction to my task's wording.
> 3. Raise gone_confirm_grace to >= 287s and assert exactly as my task words
>    it. The doc explicitly rejects this ('~60s scale, not SPAWN_GRACE's 282s,
>    which guards a different question'), and a dead agent would then read
>    'working' for ~9.5 min.
>
> Answer with a number and I will add the assertion plus its test and finish.

**What's cuttable, pointing at the exact text:**

- `"(liveness debounce)"` — a gloss on the stage name Andrew already knows from the task he assigned. Zero decision value.
- `"as 25a777e"` — the commit hash. Not needed to decide between three options; if Andrew wants to look at the commit he can ask.
- `"absent_since column, GONE_CONFIRM_GRACE=60s, both writes in the reap path, tests green (1467 passed)"` — this is a full implementation status report crammed into the first sentence of a message whose entire point is the *one unresolved thing*. None of these facts feed the three-way choice below. The "tests green" fact is the only one worth a nod, and even that only needs a word, not a clause.
- `"including the sb done a fleet needs to drain"` — this is decoration on `"kills every sb command"`, which already says the bad thing completely. Naming one specific victim of "every sb command" adds nothing since the set already includes it.
- `"(fix-options.md ~L1565-1572, and the design map)"` — a citation nobody but the agent itself would follow up on inline; it's evidence-for-the-record, not decision input. Could move to a single trailing "cites: ..." if traceability matters, but doesn't need to sit mid-sentence.
- Option 1's `", and it is broker's constant (I would not touch broker.py — only settings.toml and an assertion in status.py)"` — this is a promise about which files will be touched, which is implementation scoping, not something that changes which of the three numbered options Andrew picks.
- The quoted parenthetical inside option 3, `"('~60s scale, not SPAWN_GRACE's 282s, which guards a different question')"` — a second, redundant restatement of a point already made in paragraph 3 (the doc's assertion is about a different constant). Keeping the fact once is enough.

**Rewrite (1071 chars, 44% shorter):**

> Stage 4a is done, committed, tests green. One thing left needs your call —
> the spec contradicts itself.
>
> Task says: assert gone-confirm window >= spawn-detection window.
> SPAWN_GRACE=287s, but the confirm window is meant to be ~60s — so that
> assertion is false by definition and would crash every sb command at
> import.
>
> Turns out the doc's assertion actually describes a different constant:
> broker.ask's gone_grace (60s vs SPAWN_GRACE 287s) — which IS a real bug
> today (sb ask gives up on targets still spawning). My task paraphrased it
> onto the wrong constant.
>
> Which do you want? (1 recommended.)
>
> 1. Assert timeouts.gone_grace >= SPAWN_GRACE; raise gone_grace to 287s in
>    settings.toml. Fixes the real bug. Cost: sb ask waits ~5min before giving
>    up on a vanished target.
> 2. Assert GONE_CONFIRM_GRACE <= SPAWN_GRACE instead (debounce, not a second
>    spawn grace) — opposite direction from my task's wording.
> 3. Raise gone_confirm_grace to >=287s, assert as literally worded. Doc
>    explicitly rejects this scale; a dead agent reads 'working' for ~9.5min.
>
> Reply with a number.

This is the tightest of the three originals (it's a genuinely hard technical
tradeoff, most of the words are load-bearing), and it *still* had ~45% fat:
a commit hash, an implementation-status paragraph nobody needed to decide,
a doubled-up citation, and a file-scoping aside buried inside an option.

---

## Example 2 — `fix-fork-branch`, DESIGN-TRUTH conflict (2889 chars → 978)

Full original:

> I have the facts I need. Before writing code I have to resolve a conflict
> with `DESIGN-TRUTH.md`, which the brief reserved for the human.
>
> **need human input: changing what a delegated child forks from contradicts
> a confirmed DESIGN-TRUTH entry**
>
> **What I found (facts, not proposals)**
>
> - The fork only ever happens on one path: `Broker.delegate` → `_fork_for` →
>   `_attach_workspace(name)` (`switchboard/broker.py:2748`, `:2669`).
>   Everywhere else the child inherits its parent's workspace as a tab.
> - `_attach_workspace` defaults `base=BASE_BRANCH`, and `BASE_BRANCH` is
>   `origin/main` (`defaults/settings.toml:111`). `_fork_base` then fetches
>   it. So **every** child of an agent with no worktree — i.e. every child of
>   a top orchestrator — starts at `origin/main`, whatever branch the human's
>   checkout is on.
> - Confirmed on myself: this worktree was created at exactly `origin/main`,
>   missing all 17 commits on `fix-sb-path`. That is the finding in the
>   brief, reproduced.
>
> **The conflict**
>
> - `DESIGN-TRUTH.md:279` — *"A workspace forks from `origin/main` by
>   default."* — confirmed 2026-08-09.
> - `DESIGN-TRUTH.md:34-36` — *"forking from `origin/main` is what a
>   workspace does."*
>
> A delegated child's space **is** a workspace, so making it fork from the
> parent's branch changes what that entry says. The file's own rule is to
> stop rather than proceed, and the brief repeated it. So I have not written
> any code.
>
> **Questions**
>
> 1. **Does entry 279 yield to "a delegated child forks from the branch its
>    parent's checkout is on"?**
>    *Recommended: yes, narrowed rather than replaced.* Under this rule a top
>    orchestrator standing on `main` still gets `origin/main` (fetched,
>    exactly as today) — the CUJ at line 34 is untouched. Only a parent
>    sitting on a feature branch changes: its children fork from that
>    branch's tip. Nothing to remember and no flag, so C6 holds — the code
>    reads the branch. `sb start`/`sb workspace new --base` keep their
>    current meaning.
>
> 2. **Uncommitted work in the parent's checkout.** A fork is `git worktree
>    add` from a commit; a working tree cannot be inherited.
>    *Recommended: fork from the committed tip, and say so.* When the
>    parent's tree is dirty, the spawn tells the parent (and logs it) that
>    the child cannot see those changes — same shape as the existing
>    `base_fallback` signal. The alternative, refusing the spawn on a dirty
>    tree, would refuse almost every real spawn, since your main checkout is
>    nearly always dirty.
>
> 3. **Is "top-level orchestrator starting fresh still wants `main`" a case
>    that needs its own answer?**
>    *Recommended: no.* It falls out of Q1 — a fresh start is a checkout on
>    `main`, and inheriting `main` is forking `origin/main`. A detached HEAD
>    has no branch to inherit and falls back to `origin/main` too.
>
> If you say yes to 1 and 2 I will implement exactly that, add tests, and
> prove it in a throwaway clone as the brief describes.

**What's cuttable, pointing at the exact text — this is the worst offender of
the three:**

- Entire opening sentence, `"I have the facts I need. Before writing code I
  have to resolve a conflict with DESIGN-TRUTH.md, which the brief reserved
  for the human."` — pure throat-clearing. "I have the facts I need" tells
  Andrew nothing he needs for the decision. "which the brief reserved for the
  human" is restating his own instruction back to him — he wrote the brief,
  he knows what it reserved. The bold header two lines down already says the
  same thing in one line and is the one worth keeping.
- `"(facts, not proposals)"` in the section header — defining/labeling its
  own content instead of just presenting it. If the bullets are facts, they
  read as facts; the parenthetical is the agent narrating its own compliance
  with a format rule, not information.
- `"That is the finding in the brief, reproduced."` — restates the task back
  again. Andrew assigned the investigation; telling him "this is the thing
  you asked me to check" adds nothing to what to decide.
- `"The file's own rule is to stop rather than proceed, and the brief
  repeated it. So I have not written any code."` — this is justification for
  *why the agent is blocking at all*, aimed at defending the decision to
  stop rather than informing the decision itself. Andrew doesn't need to be
  told twice that the rule says to stop (the whole message already
  demonstrates that by existing) or reassured that the brief told the agent
  the same thing.
- Question 1's justification paragraph is the single largest deletable
  chunk: `"Under this rule a top orchestrator standing on main still gets
  origin/main (fetched, exactly as today) — the CUJ at line 34 is untouched.
  ... Nothing to remember and no flag, so C6 holds — the code reads the
  branch. sb start/sb workspace new --base keep their current meaning."` —
  four sentences of pre-emptive defense of a one-line recommendation. The
  load-bearing fact ("a top orchestrator on `main` still gets `origin/main`
  as today") is one clause; the rest is arguing a case nobody has challenged
  yet.
- Question 2's `"same shape as the existing base_fallback signal"` and
  `"The alternative, refusing the spawn on a dirty tree, would refuse almost
  every real spawn, since your main checkout is nearly always dirty."` — the
  second sentence argues against an option nobody proposed; cut both, or
  keep only the second at a fraction of the length if Andrew's checkout being
  usually-dirty is genuinely non-obvious to him (it isn't — it's his own
  checkout).
- **Question 3 in its entirety.** This is the clearest case of a question
  that shouldn't have been asked: the agent poses it, then answers it itself
  by explaining it's a strict logical consequence of Q1 ("It falls out of
  Q1..."). If it falls out of Q1, it isn't a decision — it's the agent
  showing its work. Forcing Andrew to read and mentally close a question that
  was never actually open is exactly the "over-analysis" he complained about.
- Closing `"as the brief describes"` — restating the task instructions back,
  a third time in one message.

**Rewrite (978 chars, 66% shorter):**

> **Need a decision: a delegated child forks from `origin/main`, never the
> parent's branch — matches DESIGN-TRUTH:279, but that's what broke this
> task.**
>
> Confirmed on myself: this worktree started at `origin/main`, missing all 17
> commits on `fix-sb-path`.
>
> Fork path: `Broker.delegate` → `_fork_for` → `_attach_workspace`
> (`broker.py:2748`), defaulting to `BASE_BRANCH=origin/main`. Every child of
> a parent with no worktree of its own inherits that, regardless of the
> parent's actual branch.
>
> 1. **Should a delegated child fork from the parent's branch instead of
>    `origin/main`?** Recommended: yes, narrowed — only when the parent has
>    its own worktree. A top orchestrator on `main` still gets `origin/main`
>    as today.
> 2. **Parent's checkout is dirty (the usual case) — child can't inherit
>    uncommitted work.** Recommended: fork from the committed tip and tell
>    the parent, same as today's `base_fallback` signal.
>
> Say yes and I'll implement, test, and prove it in a throwaway clone.

Note this rewrite also drops the `DESIGN-TRUTH.md:34-36` quote-bullet
entirely — it's a second citation for the same conclusion the `:279` quote
already establishes in the bold header, and the header alone is enough for
Andrew to go look at the file if he wants the exact wording.

---

## Example 3 — `live-mpq7k-kid`, role-permission refusal (1188 chars → 363)

Full original:

> **What I was asked**
>
> The human instructed me (via inbox) to run exactly one command and report:
>
> ```
> sb delegate "Run exactly this one command and nothing else: sb done
> \"grandchild done\"" --name mpq7k-gk
> ```
>
> **What happened**
>
> I ran it verbatim. It failed, exit code 1:
>
> > sb: a worker does not spawn agents — only a role with delegate rights
> > does (today: orchestrator). If this task is bigger than one agent, or
> > needs a decision you were not given, say so to your parent with `sb
> > done` rather than growing a tree under yourself.
>
> So this is a role-permission refusal, not a crash. I am role `worker`;
> delegation is restricted to `orchestrator`. I did nothing else and spawned
> nothing.
>
> **Questions**
>
> 1. Do you want the delegate run from an agent that has delegate rights
>    instead (e.g. have `mpq7k-lead`, the orchestrator, spawn `mpq7k-gk`)? —
>    *Recommended: yes, that's the intended path and it produces the same
>    grandchild.*
> 2. Or is this refusal itself the thing you were testing, in which case
>    nothing further is needed? — *If so, no action; I'll close out.*
>
> I'm not taking either path without your say-so, since both are decisions
> about the agent tree that weren't mine to make.

This is already the shortest and closest-to-right of the three, but even here
there's cuttable weight:

- The whole `**What I was asked**` section, including the fenced code block
  reproducing the exact command — Andrew is the one who gave that
  instruction via inbox; quoting it back to him in a labeled section adds a
  full paragraph of restating-the-task for zero new information. If the
  literal command matters as evidence, it belongs folded into the "what
  happened" sentence, not given its own header and code fence.
- `"So this is a role-permission refusal, not a crash."` — this sentence
  exists to pre-label the category of failure, but the quoted error message
  immediately above it already says that in plain language ("a worker does
  not spawn agents — only a role with delegate rights does"). Restating the
  classification of an error the reader just read is redundant.
- `"I did nothing else and spawned nothing."` — true and fine as a safety
  note, but it's answering a question nobody would ask given the two options
  below make clear nothing was spawned.
- Closing sentence, `"I'm not taking either path without your say-so, since
  both are decisions about the agent tree that weren't mine to make."` —
  this justifies *why the agent blocked at all*, which is self-evident from
  the fact that it did block. It doesn't change which of the two options
  Andrew picks.

**Rewrite (363 chars, 69% shorter):**

> Ran `sb delegate ... --name mpq7k-gk` as instructed. Failed, exit 1 —
> worker role can't delegate (rights are orchestrator-only):
>
> > sb: a worker does not spawn agents — only a role with delegate rights
> > does...
>
> 1. Want `mpq7k-lead` (orchestrator) to run the delegate instead?
>    Recommended: yes.
> 2. Or was the refusal itself the test? Then nothing further needed.

---

## Sizes at a glance

| Example | Before | After | Cut |
|---|---:|---:|---:|
| 1. teardown-fix (spec contradiction) | 1924 | 1071 | 44% |
| 2. fix-fork-branch (DESIGN-TRUTH conflict) | 2889 | 978 | 66% |
| 3. mpq7k-kid (role refusal) | 1188 | 363 | 69% |

The example Andrew would most likely call "the good one" structurally
(numbered questions, bold headers, recommendations, evidence, file:line
citations — example 2) is also the one with the most fat: two-thirds of it
was cuttable without losing anything the decision needs. The hardest,
most-technical one (example 1, three genuinely competing options) still had
roughly half.

---

## Recurring kinds of text that shouldn't survive, ranked by cost

Ranked by how much text they cost across these three examples (rough
proportion of total deleted characters), not by frequency of occurrence:

1. **Justifying the recommendation at pre-emptive-defense length.**
   By far the biggest single cost (most of example 2's cut). Pattern: state
   a recommendation, then spend two to four sentences defending it against
   objections nobody has raised — "nothing to remember and no flag, so C6
   holds," "the alternative would refuse almost every real spawn," etc. One
   clause of *why* is useful; a paragraph of pre-argued rebuttal is the agent
   litigating a case it hasn't been challenged on yet. This is the direct
   textual form of what Andrew called "over-analysis."

2. **Asking a question and then answering it yourself.**
   Example 2's Question 3 is the purest instance: posed, then immediately
   resolved by the agent's own next sentence ("It falls out of Q1..."). If
   the answer is a logical consequence the agent already worked out, it was
   never a live decision and shouldn't have been formatted as one — doing so
   forces the reader through the full weight of "a question" (read, parse,
   decide) for something that required no decision at all.

3. **Restating the task or instruction back to the person who gave it.**
   Present in some form in all three: "which the brief reserved for the
   human," "That is the finding in the brief, reproduced," "as the brief
   describes" (ex. 2, three separate times); the whole "What I was asked"
   section with a fenced code block reproducing the human's own command
   verbatim (ex. 3). Andrew already knows what he asked for. Confirming it
   back to him is the agent showing its work, not giving him new
   information.

4. **Status/implementation detail that doesn't feed the decision.**
   Commit hashes, exact test-pass counts, which specific files will or won't
   be touched, doc line ranges cited inline — real facts, genuinely true, but
   not facts that change which numbered option gets picked. Example 1's
   opening sentence is the clearest case: four implementation details
   crammed before the one sentence that matters ("it needs your call").

5. **Justifying *that* a block is happening at all.**
   "The file's own rule is to stop rather than proceed, and the brief
   repeated it. So I have not written any code" (ex. 2); "I'm not taking
   either path without your say-so, since both are decisions about the agent
   tree that weren't mine to make" (ex. 3). The act of calling `sb block`
   already proves the agent is stopping — restating the *reason it's allowed
   to stop* is defending a non-accusation.

6. **Redundant restatement of the same fact in two places.**
   Smaller cost, but present: example 1 states "the assertion is about a
   different constant" in paragraph 3, then restates the identical point
   inside option 3's parenthetical quote. Example 2 quotes two different
   DESIGN-TRUTH lines (:279 and :34-36) that support the identical
   conclusion, when one plus the bold-header summary already carries it.

7. **Category-labeling a sentence that already shows its own category.**
   "So this is a role-permission refusal, not a crash" (ex. 3), placed
   directly under a quoted error message that already says, in plain words,
   that a role lacks rights. Smallest cost of the group, but it's a tell for
   the same instinct as #1 and #2: explaining a conclusion the evidence just
   made obvious.

Patterns from Andrew's own list that did **not** show up much in these three:
term-defining and hedging were largely absent — these agents were fairly
confident and didn't hedge. The dominant costs here were justification
length and restating-the-obvious, not uncertainty-padding.

---

## Shape on screen, not just word count

Andrew's complaint named line-wrapping, paragraph density, and spacing
specifically, separate from raw length. Looking at these three as they'd
render in a narrow terminal pane (the actual reading surface, not this
markdown file):

- **Bullet sub-clauses run long enough to wrap 3-4 times each.** Example 2's
  bullet 2 — `` `_attach_workspace` defaults `base=BASE_BRANCH`, and
  `BASE_BRANCH` is `origin/main` (`defaults/settings.toml:111`). `_fork_base`
  then fetches it. So **every** child of an agent with no worktree — i.e.
  every child of a top orchestrator — starts at `origin/main`, whatever
  branch the human's checkout is on. `` — is one bullet that is really three
  facts stacked into one wrapped paragraph-as-bullet. In a ~80-col pane this
  single bullet occupies 4+ visual lines with no internal break, so it reads
  as a wall even though it's formatted as a "bullet."
- **Recommendation lines are the worst offender for wrap-without-break.**
  Every `*Recommended: ...*` line in example 2 is a run-on: the
  recommendation word, then an em-dash, then a full justifying clause, all
  on one logical line that the terminal wraps into 3-5 physical lines with
  no blank line or bullet break inside it. There is no visual signal telling
  the eye "the answer ends here, the justification starts here" — recommendation
  and justification are typographically fused.
- **No blank line between a numbered question's claim and its justification**
  in either example 1 or example 2's option lists — option/question text and
  its rationale run together in the same paragraph, so scanning for "what are
  my N choices" requires reading full paragraphs rather than jumping bullet
  to bullet.
- **Bold headers help scanability but there are a lot of them relative to
  content** in example 2 — `**need human input...**`, `**What I found (facts,
  not proposals)**`, `**The conflict**`, `**Questions**` — four section
  headers for what, after the cuts above, is under 1000 characters of
  actual content. Each header signals "new section, re-orient," which costs
  a scan-reset even when the section under it is short. Fewer, load-bearing
  headers (just the one-line problem statement, then the numbered questions)
  would cut vertical scanning without cutting information.
- **Example 3's fenced code block** (reproducing the exact `sb delegate`
  command) forces a visual mode-switch — prose, then a monospace block, then
  prose again — for content (the human's own instruction) that didn't need
  to be reproduced at all, let alone in its own visually-distinct region.
- **Example 1, once trimmed, is the one whose shape stays good even at its
  original size** — three short paragraphs, one visually distinct question
  line, three options each under 2 wrapped lines. It's evidence that a
  genuinely irreducible decision doesn't have to look like a wall if each
  option is kept to one clause of "what" plus one clause of "cost," with a
  line break enforced between them.

The throughline: it isn't only that there are extra *sentences* — it's that
existing sentences fuse claim-and-justification with no typographic seam,
so even a reader who wants to skip the justification can't find where it
starts without reading it first.
