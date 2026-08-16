# Scout: does main already stop a parent double-blocking after handing off to a child?

Verdict: **not fixed** — the scenario in the brief isn't the case PR #65's
handoff rule addresses.

## What the scenario actually is

Dispatcher relays the human's questions DOWN to a child, tells the child to
answer the human directly and block, then ALSO calls `sb block` itself before
the child has done anything. Two rows wait on the human for one question.

This is a **pre-emptive dual block**: the parent hands off *before* any work
is reported, and blocks anyway. It is not the same shape as the rule that
exists.

## What PR #65 actually added (`git show d854682`)

The handoff rule it introduces is scoped to a different failure: a dispatcher
relaying a child's *already-finished* work a **second time**. The commit
message says so directly:

> "Handoff (protocol.md, dispatcher.md, lead.md, DESIGN-TRUTH.md): a parent
> may report a child's work once and may not become the channel for the
> conversation about it... the failure it fixes was a dispatcher relaying a
> second time and paraphrasing findings it did not hold."

## The relevant text, quoted

`defaults/protocol.md:270-281` (the protocol-level rule, injected into every
agent's system prompt):

> "You may report a child's work once; you may not become the channel for
> the conversation about it... Restore the child if it is closed, `sb tell`
> it exactly what to explain and to `sb block` once it has, then `sb done`
> yourself... One question decides which you are doing: has this child's
> finished work already reached the person once? **The first time is still
> yours to relay and block for, in the child's own words** — a person should
> not have to go talk to every child just to learn its piece landed.
> Everything after that first report is the handoff..."

`defaults/roles/dispatcher.md:240-249` (dispatcher-specific elaboration):

> "Putting a finished piece of work in front of the person is your one
> report, and you must make it... **The first time a child reports done**,
> write in your chat... and then `sb block`... Anything after that first
> report — they come back wanting more on work already reported — is the
> handoff the protocol describes."

## Why this doesn't cover the scouted scenario

Both passages are written around **the child having already finished and
reported**, with the discriminator being "has this reached the person once
already?" The dispatcher-brief scenario is upstream of that: the dispatcher
delegates the *answering itself* to the child ("answer the human directly and
block") before the child has done or reported anything. Read literally, the
protocol text at line 276 explicitly tells the parent **"The first time is
still yours to relay and block for"** — i.e. an agent following this text
literally could conclude it should still block on a first report, even one
it just told a child to make directly. Nothing in either passage says "if
you've instructed the child to block directly, do not also block yourself."

An agent following this text faithfully could still produce exactly the
double-block the brief describes — the text is silent on the case where the
parent hands off the *act of blocking* itself, not just the reporting of
finished work.

I did not find any other file discussing this (checked all files matching
`sb block` under `switchboard/`: store.py, hooks.py, richboard.py, broker.py,
cli.py, validate.py, status.py — these are implementation/validation code,
not prompt text, and none of them gate on "child already blocking" logic;
I did not read them in full, only grepped for `sb block`, so I can't rule out
enforcement code there, but the brief's ask was about prompt text and the
handoff rule is prompt-only per the PR commit message).

## Confidence

High on the textual reading (direct quotes, direct commit diff). Have not
tested this live with actual agents — this is a read-only prompt-text
analysis only, as scoped.
