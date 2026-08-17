<!--
The format a design gate's message is written in, and nothing else.

AUDIENCE: the agent that owns a step whose exit condition is the design gate. It reads
this when it reaches that step — `sb presets design-gate` — writes its summary in this
shape, and blocks. Nothing here says when to run a design gate or what a gate is; that is
`sb plugin plans guide`, which is where the procedure lives. This file is the format the
procedure names.

BINDING: none, deliberately, and this is the shipped example of a preset that exists ONLY
for a step to name. It is not in any `presets.toml` list, so no spawn carries it and no
role pays for it. A format read once, at one step, on the jobs that have that step, must
not be stapled to every agent in the fleet on the chance that one of them reaches a gate.
Being unbound is what makes it free to be exact.

That it is spawn-only is convention rather than code: nothing stops `sb delegate --with
design-gate`, and nothing is going to — the design says enforcement waits until the steps
themselves are solid, and a stop hook that policed a format would be a mechanism arriving
before the thing it polices.

`DESIGN-TRUTH.md`'s rule that almost none of the human-facing guidance may become
something to copy is set aside here, and the spec says so in as many words: a step may
specify an output format exactly. This is that exception, and it is the only reason a file
this prescriptive is allowed to exist.

The bullet rule is the standing human-facing one, not a tighter one — around twelve words,
up to about twenty where a point genuinely branches. It is written down rather than
assumed because the case that needs the loose end of the range is exactly the case a
behavioural contract is made of: one proposition with three conditions fragments into four
bullets that each lose which condition governs which branch.
-->

# design-gate

The format for a design gate's message: what you write after planning and before
implementing, immediately before you block.

Two sections and no more. First what is causing the problem. Then what the fix will be —
its behavioural contract, ordered step by step for his understanding, rather than a
step-by-step capture of the implementation.

Bullets indent in three levels, `-`, then `---`, then `-----`:

    - The plan's steps are held on the plan, and read nowhere else.
    ---
    - A gate is a step's exit condition, so no second step holds it.
    - Where a gate needs him the owner blocks, and answering it clears both.
    -----
    - A gate that is skipped keeps its reason on the step, where a scan sees it.

Bullets run short — around twelve words, and up to about twenty where the point genuinely
branches. A condition with its fallback stays in one bullet: splitting it into two loses
which condition governs which branch, which is the whole content of a behavioural
contract.

Anything that does not fit points at a fuller artifact — a brief, a design note, a diff —
rather than being crammed in. The short version is what he reads; it must never be the
only version he can get to.

Where the change spans two worktrees, name the other plan. Plans are isolated as state and
that isolation must not reach this message: asking him to approve half a contract twice,
with the sentence that would explain it ruled out, is worse than a longer message.

Then block, and let him answer the block. Answering you is what clears the gate — there is
no verb that clears one through the plan, and you do not tick the step until he has
answered.
