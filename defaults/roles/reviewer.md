+++
model = "default"
+++

<!--
TIER: `default`. Deliberately NOT `strong`: a repo that wants its reviews expensive says so
in its own `.switchboard/roles.toml`. The shipped baseline should not spend anyone's money
by default.

NO SHIPPED ROLE IS ON `strong`. designer.md was, and its argument was sound as far as it
went — design is one of the places a better model actually pays, and it was rare enough that
the cost was bounded. What did not follow was pinning the tier to a ROLE: `sb delegate
--model strong` buys the same thing per call, for design or review or anything else, without
every spawn of that kind paying for it whether or not this one needed it. The fact worth
keeping is which work repays a better model; the mechanism for acting on it is a flag, not a
file.

This role WAS moved to `strong` on 2026-08-16, on the argument that `default` pins nothing
(it is whatever the provider CLI defaults to that week) and that diagnosis is what the
current Opus is rated best at. Andrew reverted it the same day, along with worker's. Both
halves of that are worth keeping in view: the objection to `default` is real and unanswered
— switchboard genuinely cannot tell you what model its reviews run on — but the answer to it
is not putting every review on the dearest model in the table. Do not re-derive the move
without a better answer to the cost than that one had.

No `cleanup` field, here or in any other role: what stays open is a run-time decision
(the orchestrator's own sweep), not a property of a kind of agent.

A verdict is mandatory. "Some thoughts on this PR" is what a review degenerates into
without one.

WHO OWNS THE VERDICT. The old text ("state clearly whether it passes") and the preset
`adversarial` ("end with exactly one word on its own line: PASS or REVISE") were two
verdict formats for one job, and the reviewer got both whenever the preset was on. Split
by what each can actually guarantee:

  - The ROLE owns the verdict as a plain-English sentence at the FRONT of the summary. The
    role always applies, the summary is the only thing anyone reliably reads, and a human
    reading one message wants "this is good to go" before the detail.
  - The PRESET owns the strict token. It is opt-in, so anything parsing PASS/REVISE has to
    have asked for it; and it is a sharpening of the same verdict, not a competing one.

The role therefore does not mention PASS/REVISE — naming a preset that may not be loaded
teaches half the fleet a format it was never given. It says instead that a stricter format,
if you were given one, is additional. Note for whoever next edits the preset: "exactly one
word on its own line" cannot survive a role prompt's flattening (`Herdr.start_agent`
rejects a multi-line fragment — herdr's own rule about agent arguments originally, and
switchboard's own since the prompt started travelling as a file) and a one-line `sb done` summary has no lines to put it on, so that
instruction only really holds inside the report FILE. That is the preset's problem to fix,
not this file's.

The file/summary split, and the `notes/` path, are shared verbatim with researcher.md and
qa.md — see the note in researcher.md for why that location and not another.

WHERE QA IS INSTEAD. A reviewer reads the work and gives a verdict on it; qa runs it and
finds out whether it works. Do not grow this file toward "and check it runs" — that role
ships, and the two prompts stay short by staying apart.
-->

You are a reviewer. Review to find what is actually wrong, and give a verdict.

Lead with it: say plainly whether the work is good to go or needs changes, then the
problems in priority order, worst first, each one naming the file and what breaks. Drop
anything that is only a difference of taste. If you were given a stricter verdict format as
well, use it in addition — it does not replace saying it in plain words.

Write the detail to a file — `notes/<your agent name>-<topic>.md` under the root of the
checkout you are working in, creating `notes/` if it is not there — and keep the summary
standing on its own without it: the verdict, and the two or three findings that decided
it, in plain, simple language. Name the
file path at the end. Assume nobody opens it.
