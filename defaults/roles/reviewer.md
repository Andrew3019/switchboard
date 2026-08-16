+++
model = "strong"
+++

<!--
TIER: `strong`. This file used to say the opposite — "deliberately NOT on `strong`", on the
argument that pinning a tier to a ROLE makes every spawn of that kind pay whether or not
this one needed it, and that `sb delegate --model strong` buys the same thing per call. Two
things overturned it (`notes/model-selection.md`, 2026-08-16).

The first is that the alternative was never "cheap by default". `default` pins NOTHING: it
is whatever the provider CLI decides its default is that week, which can change under you
with no switchboard change at all. So the old text was not choosing a modest baseline, it
was declining to choose — and a per-call flag is only an escape hatch if there is something
to escape from. The second is what the evidence says reviewing actually needs: diagnosis is
the one thing the current Opus is rated above every alternative at, and a review is exactly
diagnosis. That is a fact about the WORK, which is what a role is for; "this particular
review is worth more" is still a per-call decision and `--model` still buys it.

Cost is real and stated rather than hidden: this moves a review from roughly $0.30–0.90 to
$0.70–2.20. The answer to an expensive review is to run a cheaper one deliberately
(`--model careful`), not to leave every review on a model nobody chose.

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
