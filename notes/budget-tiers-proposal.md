# Proposal: a length aim for human-facing bullets (v2, simplified)

Supersedes the earlier version of this note (tier scheme, claim counting, S/M/L
table). Andrew's verdict on that version, verbatim:

> "even this is a little too complex for something as simple as the agent's output
> tone. dumb this down a little, dont causing over anchoring or regression with these
> restrictions. what 'general' changes are we making. e.g. fixed word counts and line
> counts based on 'abstract' and 'arbitrary' complexity levels. etc. redo this"

So: no tiers, no claim-counting test, no table, no named categories. Just the plain
instruction Andrew already gives by hand — "max 15 words each, sometimes 10, sometimes
20, depends how complex" — written into the prompt in the same register, plus the two
or three rules from the old proposal that are genuinely simple and were his own
complaints.

## The wording

### `defaults/protocol.md` — replacing lines 244–256

Current text:

> Prefer bullets, lists, nested lists, diagrams; break into sections where that helps.
> Their eye goes down the message, not along the line, so leave it places to stop:
> nothing that runs on unbroken, space between one idea and the next. Length you cannot
> cut you can still break up. Open with one line restating what you were asked, always.
> Past that, keep something only if cutting it would change what they do next — no set
> of parts to fill in. Options must be comparable without rereading, and the seam
> between what you ask and what you recommend must show before either is read. Clipped
> phrasing is welcome on scaffolding — drop articles, copulas, hedges, filler — but
> never a preposition, a comparative, or any word doing disambiguating work; shape is
> the bigger lever than register. Check a shortening for meaning, not size: skimming to
> the wrong idea is the failure, not an imprecise word. None of this is a shape to copy
> — no template, no length to hit — and none of it governs what only agents read: `sb
> tell`, a summary a parent agent reads, a task you write for a child.

Proposed replacement (changes bolded in this note only, not in the actual text):

> Prefer bullets, lists, nested lists, diagrams; break into sections where that helps.
> Their eye goes down the message, not along the line, so leave it places to stop:
> nothing that runs on unbroken, space between one idea and the next. **Keep each
> bullet to a line or two — a plain fact in ten words or so, a genuinely tangled one up
> to about twenty, never a paragraph wearing a bullet. One idea per bullet: a second
> independent point is a second bullet, not the same one stretched with a dash or
> semicolon. And when several short items sit side by side — PRs, files, names — don't
> run them together on one line; give each its own line, or a table if they share the
> same fields.** Length you cannot cut you can still break up. Open with one line
> restating what you were asked, always. Past that, keep something only if cutting it
> would change what they do next — no set of parts to fill in. Options must be
> comparable without rereading, and the seam between what you ask and what you
> recommend must show before either is read. Clipped phrasing is welcome on
> scaffolding — drop articles, copulas, hedges, filler — but never a preposition, a
> comparative, or any word doing disambiguating work; shape is the bigger lever than
> register. Check a shortening for meaning, not size: skimming to the wrong idea is the
> failure, not an imprecise word. **Beyond the length aim above, none of this is a
> shape to copy** — no template, no fixed section list — and none of it governs what
> only agents read: `sb tell`, a summary a parent agent reads, a task you write for a
> child.

That's the whole change: one sentence of length guidance, one sentence on one-idea-
per-bullet, one sentence on not cramming a line, and a two-word edit to the closing
sentence so it stops contradicting the new guidance. Nothing here asks the agent to
classify, count, or label anything before writing.

## The `DESIGN-TRUTH.md` passage — Andrew's to paste

`DESIGN-TRUTH.md:225-228` currently reads:

> **None of this may be turned into something to copy.** No template, no worked
> example, no word or line limit, no fixed section list, no "here is what a good one
> looks like". Anything an agent can pattern-match and reproduce collapses every
> message into one shape and gets gamed on length instead of judgement. — confirmed
> 2026-08-14

That reasoning is why the last version of this proposal built a taxonomy instead of a
number — trying to dodge it. Andrew's answer was that the taxonomy is worse: it's its
own mould, just a fancier one, and it costs the agent's attention on classifying
instead of writing. The honest fix isn't a cleverer structure, it's accepting a plain,
un-clever length aim and trusting judgement to apply it loosely — the same trust this
section already extends everywhere else (register, cutting, spacing).

Proposed replacement:

> **A rough length aim, not a limit to hit.** Bullets run short — a plain fact in
> around ten words, something genuinely more tangled up to about twenty — judged by
> feel, not counted or labelled. This trades away the airtight version of "no mould"
> the line above states, because Andrew's stated cost of no aim at all (bullets he
> cannot skim) is worse than the cost of a loose aim occasionally drifting long. What
> it doesn't trade away: nothing here is a template, a worked example, or a category to
> sort a bullet into before writing it. It's the same instruction Andrew gives by hand
> — "depends how complex, sometimes ten words, sometimes twenty" — asked of the agent
> instead of decided for it. — proposed 2026-08-16, pending confirmation

### Knock-on edits (per the standing re-read-the-whole-doc rule)

- `DESIGN-TRUTH.md:181-184` (the bullets/lists paragraph) should pick up the same two
  short sentences as the `protocol.md` edit — one idea per bullet, several short items
  don't share a line — or it will read laxer than the paragraph two entries down from
  it.
- `DESIGN-TRUTH.md:225` itself needs its header changed from "None of this may be
  turned into something to copy" since that's no longer quite true; the replacement
  above already carries a new header for this reason.
- No other passage in the Human-facing output section needs to move — the cut-floor
  rule (194-197), the compression-for-meaning rule (204-208), and the options-
  comparable rule (210-214) are untouched and still correct standing next to a length
  aim instead of a hard limit.

## Worked rewrites

Same four real bullets from the brief, rewritten against the plain aim above — no
tier labels, just "short, one idea, split what's crowded."

**1.**
> Both remaining closes now resolve through the same Broker._close_target as cleanup.
> _stop_panes (sb workspace close) refuses and deletes nothing when a row's recorded
> pane can't be proved its own — --confirm does not lift it, intent is not identity.
> _close_board leaves the pane and logs board_close_refused but still drops the meta
> row, so an agent's own close isn't the board's hostage.

→
- Both closes now route through the same check as cleanup.
- Workspace close refuses and deletes nothing if pane ownership can't be proven —
  `--confirm` doesn't override it.
- Board close leaves the pane but still drops its row, so an agent's own close no
  longer blocks the board.

**2.**
> Proven live in two isolated clones, before and after, for both paths: before, clone
> A's workspace close and its board close each killed clone B's live agent; after, both
> refuse and B survives.

→
- Verified live in two clones: before the fix, either close killed the other clone's
  live agent.
- After the fix, both refuse and the other agent survives.

**3.**
> a board pane id recycled onto another board is invisible to herdr, and a workspace
> close blocked by this refusal has no escape hatch until the stranger holding the
> pane goes.

→
- A board pane id recycled onto another board is invisible to herdr.
- A workspace close it blocks has no escape hatch — you wait for the other pane to go.

**4.**
> Merged: #55 worktree leak · #56 cleanup aliveness · #57 interrupt delivery · #58
> --force subtree · #59 ghost rows · #60 auto-mode dialog · #61, #63 close-by-identity
> · #62 dead-parent recording

→
> Merged:
> - #55 worktree leak
> - #56 cleanup aliveness
> - #57 interrupt delivery
> - #58 --force subtree
> - #59 ghost rows
> - #60 auto-mode dialog
> - #61, #63 close-by-identity
> - #62 dead-parent recording

## Flag on the sibling proposal (`notes/handoff-wording-proposal.md`)

Not rewriting it — Andrew didn't criticize it, and it was the budget proposal, not
this one, that drew his complaint. Checked it against the same "is this a taxonomy or
a plain instruction" lens anyway, since he was reacting to a message summarizing both.

It doesn't have the over-machinery smell. It's one discriminator — "has this child's
finished state already reached the person once?" — not a scored or labelled scheme,
and answering it doesn't require classifying anything, just noticing whether this is a
repeat visit. The three-verb sequence (restore, tell-then-block, done) is concrete
mechanics, not invented abstraction, and it's the same three verbs every time rather
than a menu. The one thing worth Andrew's eye, not a rewrite: the near-identical
paragraph is proposed for three places (`protocol.md`, `dispatcher.md`, `lead.md`).
That's deliberate — the diagnosis it builds on found the rule missing from
`dispatcher.md` specifically because it only lived in `lead.md` — but it's still three
copies of the same paragraph to keep in sync if it's ever edited again, which is a
smaller version of the same maintenance cost the tier table had. Worth noting, not
worth blocking on.
