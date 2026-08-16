# Scout task: does main already prevent a parent blocking on behalf of its child?

SCOUT ONLY — read and report. Change nothing, commit nothing, write no fix.

## The situation that happened

A dispatcher relayed the human's questions down to its child, told the child to
answer the human directly and block — and then the dispatcher ALSO called
`sb block` itself. The child blocked as intended. Result: two rows on the board
waiting on the human for one question.

## Question to answer

Does the prompt text on latest main (this worktree, commit d854682, which
includes PR #65 "Length aim, Where we are now, and the handoff rule") already
stop a parent from calling `sb block` once it has handed the question to a child
that is itself blocking?

## What to find

1. Every place in the prompt/role text that talks about `sb block`, handing a
   conversation over to a child, waiting on a human, or when a parent should
   block. The prompt text lives under `switchboard/` (role definitions, protocol
   text, presets) — find where, don't assume.
2. Quote the exact relevant lines, with file path and line numbers.
3. Judge it as an agent reading it would: does that text tell the parent NOT to
   block once it has handed the question down? Or is it silent/ambiguous — could
   an agent following it faithfully still double-block?
4. Look specifically at what PR #65 added (`git show d854682`) and whether that
   addition covers this case or only adjacent ones.

## Report back

A short verdict — already fixed / partially fixed / not fixed — plus the quoted
evidence with file:line references. Do not propose or write a fix.
