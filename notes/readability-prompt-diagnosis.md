# Readability prompt diagnosis (read-only)

Scope: why human-facing text from switchboard agents is still unreadable to Andrew,
despite the 2026-08-14 "human-facing output" pass (commits `3c07885`..`e2c5637`,
`f1aea28`, `c37136a`). Two separate complaints in the brief, treated separately below:
(A) list/table formatting inside a message, (B) the dispatcher piping a follow-up
Q&A through itself instead of letting the agents who hold context talk to Andrew
directly.

## A. Formatting: bullets too long, prose instead of lists/tables

### A1. There is no length constraint anywhere, by explicit design

`defaults/protocol.md:254` (human-facing output paragraph): "None of this is a shape
to copy — no template, no length to hit". `DESIGN-TRUTH.md:225-226`: "No template, no
word or line limit, no fixed section list... Anything an agent can pattern-match and
reproduce collapses every message into one shape and gets gamed on length instead of
judgement."

This is not an oversight — it is a confirmed decision (2026-08-14) reacting to an
earlier version of the rule that specified length/shape and got treated as a mould.
But it means the one number Andrew keeps repeating — "1-2 lines per bullet, I read in
a half-width pane" — is *nowhere in the prompt as a number*, on purpose. What the
paragraph gives an agent instead is a test ("does skimming convey the right idea") and
a property ("places for the eye to stop"), both of which are satisfiable by a bullet
that is accurate, skimmable-in-principle, and still three lines long in a narrow pane.
Nothing measures pane width or line count, so an agent has no way to fail its own
output against the actual constraint Andrew has. This is the top root cause: the
concrete, mechanically-checkable ask ("1-2 lines") was traded away for a judgement
call, and the judgement an agent reaches is systematically looser than what a
half-width pane needs.

### A2. "Cut only if it changes the reader's next move" pulls toward density, not brevity

`protocol.md:248-249`: "keep something only if cutting it would change what the reader
does next." `DESIGN-TRUTH.md:194-197` (same rule). This is a *floor*, not a target — it
tells the agent what it may not remove, never what it should remove beyond that. An
agent that isn't sure whether a clause is load-bearing defaults to keeping it (the
brief's own example bullet — "_stop_panes (sb workspace close) refuses and deletes
nothing when a row's recorded pane can't be proved its own — --confirm does not lift
it, intent is not identity" — is one bullet built entirely out of clauses each
individually defensible under this test). Nothing in the rule set trades off "keep
this detail" against "keep this readable"; only the untested skimmability test is
supposed to catch it, and in practice doesn't (see A4).

### A3. "Options must be comparable" and "compression checked for meaning" add caution, not compression

`protocol.md:249-253` / `DESIGN-TRUTH.md:204-214`: both rules are about *not losing or
distorting meaning* when compressing. They are correct rules on their own terms, but
they sit right next to the cut-test with no counterbalancing rule that says information
loss is *acceptable and preferred* past a point. Andrew's brief is explicit that he
wants the opposite trade: "it's fine to lose some information/context as long as it
isn't crucial... word for word I could understand 90%... what I want is 70%
understanding at a skim." The prompt currently only concedes that losing information
is acceptable via the single "cut only if it changes the next move" line — a much
higher bar than "cut if it isn't crucial," and there is no line telling the agent 70%
retention is an acceptable, even desired, target. The prompt's stated tolerance for
loss and Andrew's stated tolerance for loss are different sizes, and only the smaller
one is written down.

### A4. Devices are named, never required, and nothing enforces "one idea per line"

`protocol.md:244-247`: "Prefer bullets, lists, nested lists, diagrams... nothing that
runs on unbroken, space between one idea and the next." "Prefer" is the only verb —
there's no instruction that a fact needing two independent claims (e.g. "resolves
through the same method as cleanup" + "refuses and deletes nothing when identity can't
be proved") becomes two bullets rather than one. The observed failure — a "bullet" that
is actually two or three sentences joined by dashes and semicolons — is legal under
this wording: it is technically a bullet, it does use "—" as a break, and the rule
never says a bullet may hold only one idea. Tables are named nowhere in `protocol.md`
at all (only in `DESIGN-TRUTH.md:181-182` and `roles.md`... actually not roles.py, see
below) even though Andrew explicitly names them in his brief ("so much better formatted
as a table or a list").

### A5. The "merged PRs" list — Andrew's clearest complaint — has no home in the rules at all

The specific example he flags as needing a table (`- Merged: #55 worktree leak · #56
cleanup aliveness · ...`) is a flat run of eight short items separated by `·`. This is
not a bullet-density problem, it's a *single line holding eight facts*. None of A1-A4
addresses a single overloaded line — the rules all talk about bullets/paragraphs, never
about a line that itself needs to become a list. There's no rule an agent could point
to that says "eight comma/dot-separated items belong one-per-line," so this shape is
invisible to the current wording; it slides in as one "bullet."

## B. The dispatcher piping Q&A through itself

### B1. The rule that would have stopped this exists, but only in `lead.md`, not `dispatcher.md`

`defaults/roles/lead.md:236-238` (the actual prompt, not the comment): "Synthesising
your children's work is your job, so do it. What you must not become is a permanent
proxy: when someone needs to go deep on something a child owns, name that child and
point them at it rather than relaying every following exchange through yourself."

This is close to word-for-word what Andrew asked for in the brief. It exists. But the
agent in the transcript identifies itself as a **dispatcher** ("only this dispatcher is
alive"), and `defaults/roles/dispatcher.md` has no equivalent sentence anywhere. Its
only rule covering an incoming follow-up is: "When something arrives about work you
have already dispatched, it belongs to the child that owns it: pass it on with `sb
tell <name> "..."` rather than answering it yourself" (`dispatcher.md:228-231`) — this
covers forwarding the question in, but says nothing about what happens on the way back
out. The only rule about the way back out is: "write in your chat... which child said
about where it stands — its words, not a summary you invented — and then `sb block`"
(`dispatcher.md:233-240`) — i.e. the dispatcher is explicitly told to stay in the loop
and relay, with the only safeguard being "quote, don't invent." There is no "point
Andrew at the child directly" escape hatch for a dispatcher at all. The lead role got
the fix; the dispatcher role — the one in the actual transcript — did not.

### B2. Even the "quote, don't invent" safeguard was violated in the transcript, compounding B1

`dispatcher.md:236`: "its words, not a summary you invented." What the transcript shows
instead is entirely dispatcher-authored analytical prose ("It's a contradiction, not a
confirmed second bug... Most likely: the first turn did run briefly, the modal came up
at its end..."), not the children's own text. So this is a second, independent failure
on top of B1: the one rule the dispatcher did have, it did not follow. That the
dispatcher also had no "hand off directly" option (B1) made this failure more costly
than it would have been under `lead.md`'s wording, because there was no sanctioned
alternative to reach for.

### B3. No rule anywhere states the general principle Andrew asked for

His brief says outright: "this should be a design truth or principle somewhere." It
partially is — `lead.md`'s "not a permanent proxy" line — but nothing in
`DESIGN-TRUTH.md` states it as a product decision the way the human-facing-output
section states its rules; it lives only as an inline comment/prompt fragment in one
role file (`lead.md`) and is entirely absent from the sibling role file
(`dispatcher.md`) that actually governs the agent in his example. A rule that exists in
exactly one of two structurally-parallel prompts is a rule the *next* dispatcher will
still miss.

## Ranked root causes

1. **No length constraint exists, by design, and the tests substituting for it don't
   catch pane-width overflow.** (`protocol.md:254`, `DESIGN-TRUTH.md:225-226`) — this
   is a direct, confirmed collision between DESIGN-TRUTH's "no line limit, ever" stance
   and Andrew's concrete, repeated ask for one. Fixing A without touching this
   collision isn't possible; it needs Andrew's own call since only he edits
   DESIGN-TRUTH.
2. **The "permanent proxy" fix landed in `lead.md` but was never carried into
   `dispatcher.md`**, and the dispatcher is the role actually running the top of the
   tree in Andrew's example. This is the most surgical, lowest-risk gap: the wording
   to copy across already exists and is already Andrew-approved in spirit (it's not a
   new rule, it's an uncopied one).
3. **The cut-test's floor ("keep only if it changes the next move") has no matching
   ceiling** telling the agent to actively prefer fewer, coarser claims — the prompt's
   tolerance for information loss is narrower than Andrew's stated tolerance (70%
   understanding at a skim, explicitly "fine" to lose the rest).
4. **A single overloaded line (the "Merged: #55 · #56 · ..." case) isn't addressed by
   any rule** — every readability rule talks about bullets or paragraphs, none about a
   dense single line needing to become its own list/table.
5. **The dispatcher didn't even follow the (weaker) rule it did have** — quoting
   children's own words instead of inventing prose — which is an execution failure
   layered on top of #2, not a wording gap by itself, but worth naming because fixing
   #2 alone won't guarantee this doesn't recur.
