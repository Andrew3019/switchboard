# Proposal: name the handoff, stop the relay

Builds on `notes/handoff-prompt-diagnosis.md` (read-only diagnosis, not redone here).
This is wording only — nothing in this repo has been edited except this note.

## The one-line fix

Give the pattern Andrew described a name — **handoff** — and a fixed verb sequence, then
draw one bright line for when to use it instead of relaying. Put the definition in
`protocol.md` (every role reads it, so it can't go missing from one role file the way it
did for `dispatcher`), and have `dispatcher.md` and `lead.md` each point their own
report-writing paragraph at it.

## The discriminator

One question, answerable before you write anything:

> **Has this specific child's finished (or blocked) state already reached the person once?**

- **No, this is the first time** → relay it yourself. A short line in the child's own
  words, then block (dispatcher), or folded into the cohort synthesis (lead). Unchanged
  from today — a person should not have to go talk to five children just to learn five
  things landed.
- **Yes, and they're back for more** → **handoff**. A follow-up question, a push for
  detail, a request to defend or explain the reasoning — anything that needs the child's
  own thinking, not a line you can quote — routes straight to the child. No judgement call
  about how deep or how contestable it is; "already reported once, and back again" is
  enough by itself.

This is exactly what went wrong in the transcript: the two leftovers had already been
reported once ("Two things left on your desk..."). "explain both more?" was a return visit
to content already delivered — a textbook handoff — and the dispatcher relayed again
instead.

## The exact wording

### `defaults/protocol.md` — new paragraph (shared by every role)

Insert after the `sb block` mechanics paragraph, before "Who reads it decides this...".
This is the one canonical definition; the role files below don't repeat it, they use it.

```
A parent may also point a human at a child instead of speaking for it — a handoff, not
another relay. Restore the child if it is closed, `sb tell` it exactly what to explain
and to `sb block` once it has, then `sb done` yourself and say, in that same message, who
they should now talk to and about what. Use it whenever someone comes back wanting more
on a piece of work already reported — a follow-up question, a push for detail, anything
that needs the child's own reasoning rather than a line you could quote. The first time a
child's finished work reaches them is still yours to relay and block for, in the child's
own words: a person should not have to go talk to every child just to learn its piece
landed. It is everything after that first report where staying in the middle is the wrong
shape.
```

### `defaults/roles/dispatcher.md:233-240` — replaces the existing paragraph

```
Putting a finished piece of work in front of the person is your one report, and you must
make it: they see an agent only when it blocks, so a child's completion that you merely
noted to yourself has reached nobody. The first time a child reports done, write in your
chat, in a line or two, which piece of work has finished and what that child said about
where it stands — its words, not a summary you invented — and then `sb block` with one
short line saying their work is finished and waiting on them. When that child reported its
task fully done, that same message is where you ask whether to close it, since you are the
agent that knows it has finished and they are the one deciding what stays on their board.

Anything past that first report is a handoff, not another line for you to relay: if the
person comes back wanting more on a piece of work already reported, restore the child if
it is closed, `sb tell` it exactly what to explain and to `sb block` once it has, then
`sb done` yourself — say, in that same message, who they should now talk to and about
what, then stop.
```

Only the second paragraph is new. The first is untouched except "When a child reports
done" → "The first time a child reports done", which is the whole of the discriminator
made explicit in the role's own voice.

### `defaults/roles/lead.md:236-238` — replaces the existing paragraph

```
Synthesising your children's work is your job, so do it. What you must not become is a
permanent proxy: when someone needs to go deep on something a child owns, that is a
handoff, not another round of synthesis. Restore the child if it is closed, `sb tell` it
exactly what to explain and to `sb block` once it has, then `sb done` yourself and say, in
that same message, who they should now talk to and about what.
```

This is the sentence the diagnosis found already existed ("point them at it") — it named
the right instinct but never said how. This version gives it the same three verbs as
`protocol.md` and `dispatcher.md`, so all three files describe one move instead of three
similar-sounding ones.

## Spot-checked against the code, not assumed

The diagnosis already traced this through `broker.py`; I re-checked the load-bearing
claims directly rather than take them on trust:

- `block()` (`broker.py:3814`) — gated only on `me != HUMAN`. Nothing stops a parent from
  telling a child to call it; the docstring itself describes it as answerable by anyone
  who can `sb tell` the blocked agent.
- `done()` (`broker.py:3703`) — its own docstring states plainly: *"Reporting done with
  children still working stays legal"*, and computes `still_working` rather than refusing.
  A parent can `sb done` while its handed-off children are still `blocked`.
- `live_descendants()` (`broker.py:4494`) counts anything in `store.LIVE_STATES` as live,
  and `defaults/settings.toml:167` sets `live = ["working", "blocked"]` — so a blocked
  child is live, and `cleanup`'s "no unread mail, and finished" gate (`broker.py:3884`)
  refuses to close it. A parent calling `sb done` cannot orphan a child it just handed the
  human off to.

All three steps of the handoff — restore, tell-then-block, parent-done — are ordinary
uses of verbs that already exist and are already unconditional on caller role. Nothing
here needs a code change.

## Where the principle lives

`DESIGN-TRUTH.md` — proposed for Andrew to paste, not applied by me.

**Add**, right after the "When work finishes" entry (currently `DESIGN-TRUTH.md:92-104`,
the passage that says "the dispatcher blocks" — this is the entry that produced
`dispatcher.md`'s unconditional relay, and the new entry has to sit next to it or it reads
as unmotivated):

```
**A follow-up on a child's report is a handoff, not another relay.** "When work finishes"
above still governs the first time a child's completion reaches me — the dispatcher or
lead writes a short line in the child's own words and blocks (or folds it into a
synthesis). What changes is anything after that: if I come back wanting more on a piece of
work already reported — explain it further, defend it, walk me through the reasoning —
that belongs to the child, not to whoever first told me about it. The parent restores the
child if needed, tells it what to explain and to `sb block` once it has, then reports
itself done and steps aside. I talk to the child directly from there; when I'm done with
it, it reports done to its own parent as usual. — confirmed 2026-08-16
```

**Fix**, to keep the document consistent: `DESIGN-TRUTH.md:258`, "A dispatcher relays; it
does not interpret," uses "relay" for the *outbound* leg — passing Andrew's task words
down to a new agent, untouched. The new entry above uses "relay" for the *return* leg — a
finished child's answer coming back up. Same word, opposite direction, and sitting a few
screens apart in the same file — left alone, the second entry reads as walking back the
first. Suggested joining clause, appended to the end of the 258 entry:

```
(This is relaying the *task* downward, untouched — a different thing from relaying a
child's *answer* back upward, which "A follow-up on a child's report is a handoff" below
now covers, and which is not always the right move.)
```

I did not find any other passage in `DESIGN-TRUTH.md` that this touches — `92-104` and
`258` are the only two that talk about what a dispatcher does with a child's report.

## The second-order failure (own analytical prose)

Even under today's weaker rule ("its words, not a summary you invented"), the dispatcher
in the transcript wrote several paragraphs of its own analysis of what each child found.
Under this proposal that failure becomes moot for exactly the case where it happened: a
follow-up ("explain both more?") is now a handoff, so the dispatcher never writes
substantive content about the child's finding at all — only a pointer to who to talk to.
The existing "its words, not a summary" language still governs the first-report case, and
that case is a short pointer by design ("a line or two"), so I'm not proposing to touch
it — the risk this raises is real for a long first report, but nothing in the transcript
tests that case, and inventing a rule for a failure that hasn't happened yet is out of
scope here.

## Walk-through: the transcript under this wording

1. **Run finishes, dispatcher writes its two-item pointer and blocks.** Unchanged — this
   is dispatcher's own first report of the whole run, not a repeat of anything, so it's
   the "no, first time" branch. Same as it did.

2. **Andrew: "explain both more?"** This is a return visit to content already reported —
   the handoff branch fires. Dispatcher restores `auto-mode-dialog` and
   `close-paths-identity` (the two agents that hold each answer), `sb tell`s each
   something like: *"Andrew wants more on [the #38 wedging / the close-path escape hatch]
   — what it is, what it looks like when it bites, whether it's worth chasing. Write that
   for him directly and `sb block` once you have — he'll read your pane, not mine."* Then
   `sb done`, saying in its chat: *"auto-mode-dialog and close-paths-identity are blocked,
   waiting on you, on the #38 wedging and the close-path questions."* It does not wait for
   either to answer.

3. **The herdr crash.** In the real transcript this hit the dispatcher mid-relay, and
   Andrew had to route the "restore my children" request through it. Under this wording
   the dispatcher is already gone by the time Andrew would be reading anything — it named
   both children in step 2, so if a crash takes one of their panes, Andrew can `sb restore
   <name>` directly. He doesn't need the dispatcher back at all for this. That's a real
   side benefit worth naming: the handoff also shortens the crash-recovery path, since the
   parent is no longer a hop between Andrew and the two agents.

4. **Andrew reads each child's block directly and goes back and forth with it in its own
   pane** — full detail, no compression, no second-hand paraphrase. This is the thing he
   actually asked for.

5. **Each child, once Andrew is satisfied, calls `sb done`.** The dispatcher is the top of
   its tree, so this is a record, not mail that needs answering (`broker.py:3703`'s own
   docstring: a root's summary "is not mail — it is a record"). Nothing further is
   required of it.

Net effect: the dispatcher's own words shrink to one line naming who to talk to, Andrew
gets the two explanations first-hand, and the file that caused this — `dispatcher.md` —
now has a second, discriminable path instead of one unconditional one.
