# Proposal: complexity-tiered length budget for human-facing bullets

Status: **proposal only**. Nothing in `protocol.md`, any role file, or `DESIGN-TRUTH.md`
has been edited. Everything below is text for a human to paste in, or reject.

Builds on `notes/readability-prompt-diagnosis.md` root causes #1, #3, #4 (no length
constraint; no ceiling on cutting; overloaded single line has no rule). Does not touch
root cause #2/#5 (dispatcher relay) — that's a different note's job.

## TL;DR

- **3 tiers, named by how many independent claims the fact needs, not by how the writer
  feels about it.** S = 1 claim, M = 2 linked claims, L = 3+ claims that truly can't
  separate. Default is S; reaching for L requires being able to name the claims.
- **Applies per bullet, not per message.** A status line and a real finding coexist in
  one handoff; forcing one tier per message just pushes the finding's detail into a
  wall or throws it away.
- **Line budget is the hard cap, word count is the aim-before-you-write guide.** Andrew
  sees lines wrap, not words counted. S/M = 1 line. L = 2 lines *or* split into a
  sub-list — writer's choice, but 2 lines is the ceiling either way.
- **Three new rules alongside the budget**: prefer fewer claims above the existing
  floor, one claim per bullet (no dash/semicolon welding), and 3+ parallel short items
  become a list, never a joined line.
- **Worked rewrites of three real bad bullets + the "Merged: #55 · #56 · ..." line**
  are at the bottom — judge the scheme on those.

## 1. The tier scheme

### Discriminator: claim count, not "complexity"

A **claim** is a subject+predicate that could be true or false on its own. "Complexity"
is unusable as a discriminator because it's the writer's own judgement about its own
output — exactly the thing Andrew's proposal is designed to route around ("instead of
picking max budget and justifying why"). Claim count is checkable by a third party: read
the bullet, list the independently-falsifiable statements in it, count them. Two agents
looking at the same fact should count the same number.

Test for whether something is a second claim: **if you wrote it as its own sentence,
would it mean something and not just repeat the first sentence?** If yes, it's a second
claim. "X resolves through the same method as Y" and "X refuses when Z" are each
independently true-or-false and neither implies the other — two claims. "X refuses" and
"X refuses because Z" are one claim with its necessary reason attached — arguably one,
arguably two; when it's this close, round down toward fewer claims (see anti-gaming).

### The tiers

| Tier | Name | Claims | Word guide | Line cap | Default? |
|---|---|---|---|---|---|
| S | **Single fact** | 1 | ~10 | 1 line | Yes — assume this until proven otherwise |
| M | **Linked fact** | 2, joined by one necessary relationship (cause→effect, before→after, rule→exception) | ~15 | 1 line | No — the unusual move |
| L | **Bundled finding** | 3+, that cannot be pulled apart without losing the finding | ~20–25 | 2 lines, or split into a sub-list | Rare — last resort |

Why 3 tiers and not Andrew's 10/15/20 as three flat word counts: a flat word budget
with no claim-count anchor is exactly the "pick a number and justify it" failure mode —
an agent facing a dense fact would just call it "20-word-complex" and stop there. Tying
each tier to a countable number of claims gives the agent a mechanical test before it
ever thinks about word count: count the claims, that's the tier, the word count follows.
The word numbers stay close to Andrew's own instinct (10/15/~20) because that instinct
was already right — it just needed a non-self-reported trigger.

### Per bullet, not per message

A message's job is to report whatever happened, and what happened is rarely
uniform — a one-line status ("PR #63 merged, CI green.") next to one genuinely knotty
proof. Forcing a single per-message tier means either the status line balloons to match
the hard finding's budget, or the hard finding gets cut to fit the status line's — and
Andrew has been explicit that the cutting failure (A2/A3 in the diagnosis) is the one he
cares about more. Per-bullet tiering lets the easy fact stay a 4-word line and the hard
fact get its full 2-line budget, without either distorting the other.

## 2. Line budget vs. word budget

They're not measuring the same thing. Word count is something the agent can compute
before it writes a character; line count is something that only exists after rendering,
and depends on pane width, which the agent doesn't know precisely. So:

- **Word count is the guide** — aim for the tier's word number while drafting, because
  it's the number the agent can act on directly.
- **Line count is the hard cap** — check the result: does it wrap past the tier's line
  limit at a half-pane width (roughly 50–60 characters)? If yes, it's over budget
  regardless of the word count, and needs cutting or splitting, not rationalising ("it's
  only 16 words, that's basically 15"). Word count is a proxy for the thing Andrew can
  actually see broken; line count is the thing itself.

This also resolves the "which one does the agent obey when they conflict" question:
line wins, because line is what Andrew is reacting to when he says a bullet is too long.

## 3. Anti-gaming

Stated honestly, this is the part most likely to erode over time.

**Default is S.** The instruction isn't "pick a tier," it's "assume S; only move up if
you can point at a second, then a third, independent claim." This inverts the framing
Andrew flagged — an agent that wants to justify going bigger has to do the justifying
*before* writing (name the claims), not after (defend the word count it already wrote).

**The cost attached to L**: before an agent may use L, it must ask whether the 3+ claims
can instead become 2–3 separate S/M bullets (or a nested sub-list under one heading).
Most facts that feel like "one complicated thing" are actually several independent
facts wearing a trenchcoat, and those split cleanly. L is reserved for the genuine
remainder — a claim, its proof, and the proof's one caveat, where splitting would
make each piece individually misleading (e.g. "proven" without what it excludes). That
remainder should be rare. If L shows up on most messages, the tier definition has
drifted and needs revisiting — that's the honest failure mode: **nothing in wording
stops an agent from quietly widening what counts as "can't be split apart" over many
messages**, the same way "no line limit" quietly widened to 3-line bullets. A word
count is at least checkable after the fact by a human skimming; whether the tier
assignment itself is honest is not something the prompt can force. This is a known,
accepted gap, not a solved one.

**What happens to a fact that genuinely doesn't fit even L**: split it. Concretely,
in order of preference: (1) two S/M bullets if the claims are actually independent,
(2) one bullet plus a nested sub-bullet if one claim is a detail of the other, (3) a
one-line pointer to a file path if the detail is real but not needed to understand the
outcome ("detail: `notes/close-paths-resolved-by-terminal-id.md`"). Splitting is not an
escape hatch back to unlimited length — each resulting bullet still carries its own
tier and budget. It reopens the gaming risk only if an agent starts splitting
*everything* to dodge the "3+ claims → look for a split" nudge on L while still writing
each half at L-length; the fix for that is the same as above — a human skimming a
message that's suspiciously all 2-line bullets will notice, same as they'd notice today.

## 4. The other readability faults

### No ceiling on cutting

Current text only has a floor ("keep something only if cutting it would change what
they do next"). Add a ceiling that tells the agent to prefer the smaller side of that
floor, not just avoid crossing it.

**Proposed addition** — joins `protocol.md`, directly after the existing cut-floor
sentence (currently ending `...no set of parts to fill in.`, line 249) and the matching
sentence in `DESIGN-TRUTH.md:190-192`:

> Above that floor, default to fewer and coarser: when a detail is defensible either
> way, leave it out. Losing detail that wasn't crucial is the expected cost of a
> skimmable message, not a failure of one.

### One claim per bullet

Current text never says a bullet holds one idea; two ideas welded with a dash or
semicolon is legal today and is the shape Andrew keeps getting.

**Proposed addition** — joins `protocol.md` right after the "nothing that runs on
unbroken, space between one idea and the next" clause (line 246) and the equivalent
`DESIGN-TRUTH.md:183-186` passage:

> A bullet states one claim. A second independent claim — even a true, relevant one —
> is a second bullet, not the same one extended with a dash or semicolon.

### The overloaded single line

Andrew's clearest example (`Merged: #55 · #56 · #57 ...`) is invisible to every current
rule because they all talk about bullets and paragraphs, never about a single line that
itself packs many items.

**Proposed addition** — joins `protocol.md` in the same spot as the bullet devices
sentence (line 244, "Prefer bullets, lists, nested lists, diagrams") and
`DESIGN-TRUTH.md:181-182`:

> Three or more short parallel items — PRs, issues, files, names — never share one line
> joined by `·` or commas. They become a list, one item per line, or a table when they
> share the same two or three fields.

### Combined block, ready to drop into `protocol.md`

Replacing the run from `Prefer bullets...` (line 244) through `...an imprecise word.`
(line 254), keeping the closing sentence separate (see §5 — it needs its own edit):

> Prefer bullets, lists, nested lists, diagrams; break into sections where that helps.
> Their eye goes down the message, not along the line, so leave it places to stop:
> nothing that runs on unbroken, space between one idea and the next. A bullet states
> one claim; a second independent claim is a second bullet, not the same one extended
> with a dash or semicolon. Three or more short parallel items — PRs, issues, files,
> names — never share one line joined by `·` or commas: they become a list, one item
> per line, or a table when they share the same fields. Length you cannot cut you can
> still break up. Open with one line restating what you were asked, always. Past that,
> keep something only if cutting it would change what they do next — no set of parts
> to fill in — and above that floor, default to fewer and coarser: when a detail is
> defensible either way, leave it out. Every bullet gets a size before it's written,
> not after: count its independent claims — one is **S** (~10 words, one line, the
> default), two joined by a necessary relationship is **M** (~15 words, one line), three
> or more that truly can't separate is **L** (~20–25 words, two lines, or split into a
> sub-list instead — try the split first). The word count is the aim while drafting;
> the line cap is the check afterward, and the line cap wins if they disagree. Options
> must be comparable without rereading, and the seam between what you ask and what you
> recommend must show before either is read. Clipped phrasing is welcome on
> scaffolding — drop articles, copulas, hedges, filler — but never a preposition, a
> comparative, or any word doing disambiguating work; shape is the bigger lever than
> register. Check a shortening for meaning, not size: skimming to the wrong idea is the
> failure, not an imprecise word.

The old closing sentence (`None of this is a shape to copy — no template, no length to
hit — ...`) is addressed separately in §5, since it's the direct DESIGN-TRUTH collision
and needs Andrew's own edit there first.

## 5. The DESIGN-TRUTH collision

`DESIGN-TRUTH.md:225-226` states the reason for no length limit: "Anything an agent can
pattern-match and reproduce collapses every message into one shape and gets gamed on
length instead of judgement." That reasoning is correct and the tiered scheme does not
escape it for free — a flat number *is* exactly that mould. The claim being made here is
narrower: **the mould is in the number, not in having a budget at all.** A flat "15
words" is copyable with zero judgement. A tier keyed to *counting claims in the specific
fact being written* forces the one judgement call the old rule was trying to protect —
deciding what the fact actually contains — before any number gets chosen, rather than
after. It's not mould-proof (see §3's honestly-stated gap: the claim-count itself can be
fudged over time), but it is a materially different failure mode than a bare number,
because gaming it requires misdescribing the fact, not just picking a big label.

### Proposed replacement passage — Andrew's to paste into `DESIGN-TRUTH.md`

Replaces the final paragraph of the Human-facing output section
(`DESIGN-TRUTH.md:225-226`, "None of this may be turned into something to copy..."):

> **A budget exists, keyed to the fact, not to the writer.** Every bullet is sized by
> counting the independent, falsifiable claims it must state: one is a **Single fact**
> (~10 words, one line — the default, assumed unless a second claim earns otherwise),
> two joined by one necessary relationship is a **Linked fact** (~15 words, one line),
> three or more that cannot be separated without losing the finding is a **Bundled
> finding** (~20–25 words, two lines — or split into several smaller bullets, which is
> tried first). The word count is drafting guidance; the line cap, checked against a
> half-width pane, is the hard constraint and wins if the two disagree. This is a
> narrower rule than a flat length limit: the number an agent reaches for is downstream
> of counting what the fact actually contains, not a target chosen and then justified.
> It does not fully escape the mould risk this section originally named — an agent can
> still misdescribe a fact as having fewer claims than it does, or round a bundled
> finding down to look linked — and that risk is accepted, not solved, because Andrew's
> stated cost of the old "no limit" rule (bullets he cannot skim at all) is worse than
> the cost of an occasionally-gamed budget (bullets slightly denser than intended). —
> proposed 2026-08-16, pending confirmation

### Other passages that need to change for consistency

Per the standing rule on this file (re-read the whole document on any addition, don't
just append):

- **`DESIGN-TRUTH.md:181-186`** (bullets/lists/diagrams paragraph) — needs the same
  "one claim per bullet" and "3+ parallel items become a list/table" sentences added as
  §4 above, or it will state a laxer rule than the paragraph that follows it.
- **`DESIGN-TRUTH.md:190-192`** (the cut-floor paragraph, "What goes in is decided by
  the reader's next move") — needs the ceiling sentence from §4, same reasoning as the
  `protocol.md` edit.
- **`DESIGN-TRUTH.md:204-214`** ("Options must be comparable" / "Compression is checked
  for meaning") — no wording change needed, but worth Andrew's eye: these rules already
  coexist with a length budget in `protocol.md`'s proposed block above, and should read
  as complementary, not contradictory, once the budget paragraph sits next to them.
- **`defaults/protocol.md:254-256`** (the closing sentence) — currently reads "no
  template, no length to hit"; this is the literal contradiction and must change
  wherever the DESIGN-TRUTH passage above changes, or the two files disagree. Proposed
  replacement for that clause only (the "none of this may be turned into something to
  copy" idea stays, minus the length claim):
  > None of this beyond the sizing above is a shape to copy — no template, no fixed
  > section list — and none of it governs what only agents read: `sb tell`, a summary a
  > parent agent reads, a task you write for a child.
- Role files (`lead.md`, `dispatcher.md`, `roles.md`) were not checked for their own
  copies of the "no length limit" language — the diagnosis note didn't find any outside
  `protocol.md`/`DESIGN-TRUTH.md`, but I haven't independently grepped them for this
  task; worth a quick grep before landing in case one has an inline echo of the old
  rule.

## 6. Worked examples

All four are real text from `notes/agent-handoff-wording-brief.md`.

### Example 1 — the welded three-claim bullet

**Before** (1 "bullet," 3+ claims, ~55 words):
> Both remaining closes now resolve through the same Broker._close_target as cleanup.
> _stop_panes (sb workspace close) refuses and deletes nothing when a row's recorded
> pane can't be proved its own — --confirm does not lift it, intent is not identity.
> _close_board leaves the pane and logs board_close_refused but still drops the meta
> row, so an agent's own close isn't the board's hostage.

**After** (3 bullets — the split-first move from §3, since these are actually
independent claims, not one bundled finding):

- Both closes now route through the same check as cleanup. **(S, 9 words)**
- Workspace close refuses and deletes nothing if pane ownership can't be proven —
  `--confirm` doesn't override it. **(M, 15 words)**
- Board close leaves the pane but still drops its row, so an agent's own close no
  longer blocks the board. **(M, 18 words)**

### Example 2 — before/after proof

**Before** (~30 words, one dense clause):
> Proven live in two isolated clones, before and after, for both paths: before, clone
> A's workspace close and its board close each killed clone B's live agent; after, both
> refuse and B survives.

**After** (2 bullets — before/after is a natural M-tier split, one claim per side):

- Verified live in two clones: before the fix, either close killed the other clone's
  live agent. **(M, 14 words)**
- After the fix, both refuse and the other agent survives. **(S, 10 words)**

### Example 3 — the "still unfixed" bullet

**Before** (~30 words, two claims joined by "and"):
> a board pane id recycled onto another board is invisible to herdr, and a workspace
> close blocked by this refusal has no escape hatch until the stranger holding the
> pane goes.

**After** (2 bullets):

- A board pane id recycled onto another board is invisible to herdr. **(S, 11 words)**
- A workspace close it blocks has no escape hatch — you wait for the other pane to
  go. **(M, 15 words)**

### Example 4 — the overloaded single line

**Before** (1 line, 8 items joined by `·`):
> Merged: #55 worktree leak · #56 cleanup aliveness · #57 interrupt delivery · #58
> --force subtree · #59 ghost rows · #60 auto-mode dialog · #61, #63 close-by-identity
> · #62 dead-parent recording

**After** (list, one item per line — the §4 "3+ parallel items" rule):

> Merged:
> - #55 worktree leak
> - #56 cleanup aliveness
> - #57 interrupt delivery
> - #58 --force subtree
> - #59 ghost rows
> - #60 auto-mode dialog
> - #61, #63 close-by-identity
> - #62 dead-parent recording

At half-pane width, the before is a wrapped, comma-soup line that has to be read
word-by-word to extract eight separate facts. The after is eight one-glance rows —
this is the case the whole scheme exists to fix, and it's also the one case a claim-count
budget alone wouldn't have caught without the explicit list/table rule in §4.
