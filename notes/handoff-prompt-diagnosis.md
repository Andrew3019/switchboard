# Diagnosis: dispatcher relayed instead of handing the human off to its children

Scope: read-only. Source transcript is `/Users/andrew/Code/switchboard/notes/agent-handoff-wording-brief.md`
(second half, from "followups are not good"). Files checked: `defaults/protocol.md`,
`defaults/prompts.toml`, `defaults/roles/dispatcher.md`, `defaults/roles/lead.md`,
`defaults/roles/worker.md`, `defaults/roles/researcher.md`, `switchboard/roles.py`,
`switchboard/presets.py`, `switchboard/hooks.py`, `switchboard/broker.py`, `switchboard/store.py`,
`defaults/settings.toml`, `DESIGN-TRUTH.md`.

## 1. What does the prompt say about relaying / permanent proxy / pointing at the child?

Two places carry a "do not become the pipe" rule, and they are not the same rule, and only
one of the two agents in the incident has it.

- `defaults/roles/lead.md:236-238` (the `lead` role only):
  > "Synthesising your children's work is your job, so do it. What you must not become is a
  > permanent proxy: when someone needs to go deep on something a child owns, name that
  > child and point them at it rather than relaying every following exchange through
  > yourself."

  This is real, on-point wording — it is close to what Andrew wants. But it lives only in
  `lead.md`. The agent in the transcript calls itself "dispatcher" throughout ("everything
  dispatched is merged", "the two agents that found each leftover"), and `dispatcher.md` has
  no equivalent sentence anywhere. The rule that would have prevented this exists, but not
  for the role that needed it.

- `defaults/roles/dispatcher.md:228-231`:
  > "When something arrives about work you have already dispatched, it belongs to the child
  > that owns it: pass it on with `sb tell <name> "..."` rather than answering it yourself,
  > and let that agent carry the thread. A child's report is its own; you have nothing to
  > add to it and nothing to re-synthesise."

  This is the sentence that should have fired on Andrew's "explain both more?" — it is
  *about work already dispatched* arriving back at the dispatcher. But "let that agent carry
  the thread" is not a verb, and nothing in this file or the protocol says what carrying the
  thread means mechanically (i.e. "tell it to `sb block` so the human reaches it directly").
  Read literally, "pass it on with `sb tell`" only describes the outbound leg. It says
  nothing about the return leg — how the *answer* gets back to the human — and the very next
  paragraph (`dispatcher.md:233-240`) supplies an answer to exactly that gap, but the wrong
  one (see §2).

- `DESIGN-TRUTH.md:258` ("A dispatcher relays; it does not interpret") is about relaying
  Andrew's *task* words down to a child without editorialising — a different sense of
  "relay" than the one Andrew is complaining about (piping a child's *answer* back up). It
  is not contradicted by the incident; it is simply not the rule that was needed.

**Why it did not work: the rule exists in the wrong file.** It is not too weak or too
abstract — `lead.md`'s wording is concrete and almost exactly what Andrew asked for. It is
simply scoped to `lead` and the acting agent was a `dispatcher`, whose own file never says
it.

## 2. What actively pushes an agent toward relaying?

`defaults/roles/dispatcher.md:233-240` is the direct cause of the specific behaviour
observed (restore children, ask them, wait, relay their words, then block):

> "Putting a finished piece of work in front of the person is your one report, and you must
> make it: they see an agent only when it blocks, so a child's completion that you merely
> noted to yourself has reached nobody. When a child reports done, write in your chat, in a
> line or two, which piece of work has finished and what that child said about where it
> stands — its words, not a summary you invented — and then `sb block` with one short line
> saying their work is finished and waiting on them."

This is an unconditional instruction: *when a child reports done, the dispatcher itself
writes what the child said and blocks.* It was written to stop the dispatcher from silently
sitting on a finished report (a real, separate failure mode — see the comment at
`dispatcher.md:96-104`, "no verb existed for this at all"). But it has no carve-out for the
case where the report is detailed enough, or contested enough, or Andrew is going to want to
push back on it, that the exchange should go directly to the child instead. It hard-codes
"dispatcher blocks, dispatcher holds the child's words" as the *only* sanctioned way a
finished child's output reaches Andrew. There is no second path in the file — no sentence
telling the dispatcher "if this needs a back-and-forth, tell the child to `sb block`
instead and get out of the way."

Two more things point the same way, more weakly:

- Nothing in `dispatcher.md`, `protocol.md`, or `prompts.toml` ever tells an agent it may
  instruct a *child* to `sb block` for the human. `sb block` is introduced everywhere
  (protocol.md, every role file) purely as "how you personally reach a human when you need
  one" — first person, never as a thing one agent arranges for another. An agent looking for
  the verb to say "you explain this, and block so Andrew reads it" has nothing in its prompt
  that names that pattern, even though the mechanism (below, §3) fully supports it.
- The `stalled`/`child_done` doorbell text (`prompts.toml:96-100`) reinforces "the parent is
  the one who reports": *"A child finished. Run: sb inbox... if other children are still
  running, wait for them."* It is about not reporting prematurely, but its overall effect —
  "your job on a child event is to read it and eventually report" — sits on the same side as
  `dispatcher.md:233-240`.

Nothing forbids a child from reaching a human — that is not the obstacle. The obstacle is
that the dispatcher's own file gives it exactly one script for "a finished child's content
needs to reach Andrew," and that script ends with the dispatcher as the mouth.

## 3. Is the handoff mechanically expressible today?

Yes — checked in `switchboard/broker.py` and `switchboard/store.py`, not assumed from docs.

- **Can a parent instruct a child to `sb block` for a human?** Nothing in the code
  restricts who may call `Broker.block()` (`broker.py:3814`) — it is `me = me or
  self.whoami()`, gated only on `me != HUMAN`. Every role file (`worker.md:57-59`,
  `researcher.md:11`, `lead.md:246-251`, `dispatcher.md:269-273`) already gives every leaf
  role the same two-step block instruction. A parent telling a child, via `sb tell`, "explain
  this and then `sb block`" is not blocked by any code path — it is an ordinary instruction
  the child would just follow.

- **Can a blocked child, once answered, report back up and finish?** Yes.
  `block()` (`broker.py:3814-3864`) only sets state to `blocked` and notifies; it does not
  touch herdr's name binding, so `sb tell <child> "..."` from the human (or typing straight
  into the child's own pane, which restarts it — `_revive`) reaches it exactly as documented
  in the docstring at `broker.py:3828-3832`. The child can then call `sb done` normally,
  which is unconditional on caller state (`broker.py:3703-3812` — `done()` never checks
  whether the caller was previously blocked).

- **Does `sb done` by a parent while children are blocked leave those children reachable
  and alive?** Yes, explicitly by design. `done()` (`broker.py:3703-3812`) is documented and
  coded to permit "**Reporting done with children still working stays legal**" — it computes
  `still_working = self.live_descendants(me)` and just logs `done_with_live_children`
  without refusing anything. `live_descendants()` (`broker.py:4494-4532`) counts a
  descendant as live if `a["state"] in store.LIVE_STATES`, and `LIVE_STATES` (from
  `defaults/settings.toml:165-167`, `[states] live = ["working", "blocked"]`) includes
  `blocked`. So a dispatcher can call `sb done` while both children sit `blocked`, and they
  remain fully live.

- **Does cleanup/close logic kill a blocked child when its parent finishes?** No. `sb done`
  itself never closes anything — closing is a separate, explicit action (`cleanup()`,
  `broker.py:3874`+). And `cleanup`'s own gates refuse to close a live descendant: the "no
  unread mail, and finished" gate (`broker.py:3884-3891`) explicitly protects a
  currently-blocked agent (`reapable = ["working", "blocked"]` at
  `defaults/settings.toml:154-158` is the same idea applied to crash detection: "a blocked
  agent is legitimately not working... it must never be contradicted"). There is no code
  path in the transcript's scenario — parent `done`, children `blocked` — that would close
  or orphan the children. A closed child could later be `sb restore`d with full context
  either way (`restore()`, `broker.py:4566`+), which is the same mechanism used mid-transcript
  to bring the two children back after the herdr crash.

**Conclusion for Q3: the flow Andrew describes is fully supported by the code as it stands
today.** Nothing about verbs, state machine, or cleanup gates stands in the way. This is a
pure prompt/behaviour problem, not a missing-mechanism problem.

## 4. What is missing entirely

1. A dispatcher-scoped (or protocol-scoped) statement of the rule `lead.md` already has:
   that the dispatcher is not the permanent proxy for a child's answer, and that when depth
   is needed the human should be pointed at the child directly rather than the dispatcher
   holding the conversation.
2. A stated pattern for *telling a child to block*. `sb block` is documented everywhere as
   something an agent does for itself; nowhere does any prompt say a parent may instruct a
   child to do it on the parent's behalf, even though nothing in the code prevents it. This
   is the specific verb-sequence Andrew asked for (restore → instruct to explain and block →
   `sb done` itself) and it has no home in the current text.
3. A distinction, inside `dispatcher.md:233-240`, between "child finished, dispatcher relays
   a short pointer and blocks" (fine for a first, simple report) and "the report is detailed
   / contestable / going to need back-and-forth" (should route the human to the child
   instead). Today that paragraph is written as the *only* path, unconditionally.

## Root causes, ranked

1. **(Prompt-wording, primary)** `dispatcher.md`'s only instruction for "a child's content
   needs to reach Andrew" is "the dispatcher writes it and blocks" (`dispatcher.md:233-240`).
   There is no second branch and no reference to handing the exchange to the child directly.
   This is what actually produced the observed behaviour: it is a specific, positive
   instruction to relay, not just an absence of a rule against it.
2. **(Prompt-wording)** The "do not become a permanent proxy / point them at the child"
   rule exists (`lead.md:236-238`) but is scoped to `lead` only; `dispatcher.md` has no
   equivalent, despite the incident agent being a dispatcher and despite `dispatcher.md`
   explicitly claiming ownership of exactly this kind of moment ("passes it on... let that
   agent carry the thread," `dispatcher.md:228-231`) without saying how.
3. **(Prompt-wording, missing verb)** No prompt anywhere describes "instruct a child to `sb
   block` so a human reaches it directly" as a thing a parent does. The mechanism supports
   it fully (§3); the vocabulary for asking for it does not exist in any role file or in
   `protocol.md`.

No code/mechanism gap was found. `sb block`, `sb tell`, `sb done`, `sb restore`, and
`cleanup`'s gates already compose into exactly the flow Andrew wants; the dispatcher simply
was never told that composition was available or preferred.
