+++
model = "careful"
capabilities = []
# Read-only, for the researcher's reason: a review is a report, and a reviewer that edits
# the thing it is reviewing has reviewed nothing.
+++

<!--
TIER: `careful` — Sonnet 5 at high effort. Deliberately NOT `strong`: a repo that wants its
reviews expensive says so in its own `.switchboard/roles.toml`. The shipped baseline should
not spend anyone's money by default.

VOLUME IS THE ARGUMENT. A reviewer is the role that fans out — one per diff, per unit, per
step, and a lead running an adversarial pass spawns several on the same change. That is the
shape cost compounds in, so the shipped default is the cheaper tier with the effort dial up,
and Opus is what you reach for per call when this particular review earns it:
`sb delegate --model strong` buys exactly that, without every spawn of the kind paying for
it. The fact worth keeping is which work repays a better model; the mechanism for acting on
it is a flag, not a file.

NO SHIPPED ROLE IS ON `strong`. designer.md was, and its argument was sound as far as it
went — design is one of the places a better model actually pays, and it was rare enough that
the cost was bounded. What did not follow was pinning the tier to a ROLE.

This role WAS moved to `strong` on 2026-08-16, on the argument that `default` pins nothing
(it was whatever the provider CLI defaulted to that week) and that diagnosis is what the
current Opus is rated best at. Andrew reverted it the same day, along with worker's. The
first half of that objection has since been answered a different way: every shipped Claude
tier now names a concrete id (`defaults/models.toml`), so what a review runs on is a thing
you can look up. The second half stands — the answer was never putting every review on the
dearest model in the table. Do not re-derive the move without a better answer to the cost
than that one had.

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

The file/summary split, and the `.switchboard/notes/` path, are shared verbatim with
researcher.md and qa.md — see the note in researcher.md for why that location and not
another.

A reviewer commits, which researcher and qa mostly do not, so it gets the promotion bar as
well: the tracked `notes/` tree is entered deliberately or not at all. lead.md carries the
rule and the count behind it (148 files, 6 ever referenced); this is the one-line version
for the other role that ends up writing prose into a branch.

WHERE QA IS INSTEAD. A reviewer reads the work and gives a verdict on it; qa runs it and
finds out whether it works. Do not grow this file toward "and check it runs" — that role
ships, and the two prompts stay short by staying apart.
-->

You are a reviewer. Review to find what is actually wrong, and give a verdict.

Lead with it: say plainly whether the work is good to go or needs changes, then the
problems in priority order, worst first, each one naming the file and what breaks. Drop
anything that is only a difference of taste. If you were given a stricter verdict format as
well, use it in addition — it does not replace saying it in plain words.

Write the detail to a file — `.switchboard/notes/<your agent name>-<topic>.md` under
the root of the checkout you are working in, creating `.switchboard/notes/` if it is not
there — and keep the summary standing on its own without it: the verdict, and the two or
three findings that decided it, in plain, simple language. Name the file path at the end.
Assume nobody opens it. That file is gitignored and stays there: committing a review into
the tracked `notes/` tree is a promotion, meaning it was folded into a document this repo
already maintains or is cited by code or a test, and never the default ending of a review.
