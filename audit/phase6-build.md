# Phase 6 build — prompts and shipping

Branch `phase6-prompts`, based on `phase5-structure` at `7847b84`. That tip is
byte-identical to `phase4-removals` — phase 5 was still being built while this ran, so
what this branch actually stacks on is phase 4's tip under phase 5's branch name. Nothing
here depends on phase 5's items; `audit/phase6-scope.md` established that item by item and
this build confirmed it, since none of the six touched a line phase 5 is scoped to change.

Source text: `DESIGN-TRUTH.md`. Analysis inherited rather than repeated:
`git show scope-phase6:audit/phase6-scope.md`. Andrew's five answers are the decisions
built to, and where a decision overruled the scoping pass it is named below.

---

## What each item required, and the test that says it happened

Every wording item's test is a **containment check** — the rule is present in the text
every agent is sent. That is honestly weaker than "an agent obeys it", and the weaker
thing is the one that can be automated: the only instrument for obedience is reading what
agents produce, which is Andrew's judgement, not a test. What containment does catch is
the failure this repo has actually had — a rule edited into one prompt and dropped from
the one that ships.

| item | change | test | result |
|---|---|---|---|
| 6.1 block reasons | `defaults/protocol.md` escalation sentence rewritten | `test_the_protocol_names_every_sanctioned_reason_to_block` — one distinguishing phrase per DESIGN-TRUTH reason, subTested | PASS |
| 6.2 human-facing output | formatting rule added beside the numbered-questions half | `test_the_protocol_asks_for_skimmable_human_facing_output` | PASS |
| 6.3 role list at spawn | `[spawn] roles` fragment + `Broker.delegate` builds it from `self.roles` | `test_the_role_list_is_generated_from_the_roles_and_not_written_down` (a repo-defined role appears with no code edited), `test_every_spawn_is_told_what_roles_exist`; live below | PASS |
| 6.4 presets apply | `sb presets <name> --apply`, `Broker.apply_preset`, `[notify] preset` | four broker tests + `test_the_third_parameter_is_apply`; live below | PASS |
| 6.5 shipping | default shape + merge approval, in the protocol so every role gets it | `test_the_protocol_states_the_default_shape_of_shipping_work`, `test_no_shipped_prompt_lets_an_agent_merge_without_asking` | PASS |
| 6.6 disjoint files | `orchestrator.md` "Plan, then re-plan" | `test_a_lead_is_told_to_assign_disjoint_files_not_just_to_serialise` | PASS |

Each of the six fails on the parent commit — 6.3 and 6.4 because the code does not exist,
the other four because the phrase is not in the text.

### 6.1 — the five reasons, plus the sixth Andrew kept

The shipped sentence named three triggers, two of which mapped onto DESIGN-TRUTH's five.
It now names all five, in DESIGN-TRUTH's own order, plus the ambiguous-instruction trigger
that was already there. The scoping pass recommended narrowing that one into the
design-question reason; Andrew overruled it ("this is fine, it should be blocked"), so it
stays as a standing trigger of its own.

Two things kept deliberately:

- **"a tool fails twice"** survives as the concrete form of *being blocked on running some
  command*. The general phrasing alone would lose the threshold, and the threshold is what
  stops an agent retrying a broken tool all afternoon.
- **"never do work you were told to delegate"** survives — it is not one of the five, it
  was already there, and it is a real guardrail with a live failure behind it.

6.1 and 6.5 were done in one pass, as the scoping pass asked: the fifth reason and the
merge rule are the same situation seen from two sides, and the text says so in one breath
("an open pull request waiting on a merge is exactly that case").

### 6.3 — generated, not written down

`Broker.delegate` now sends `spawn.roles`, filled from `", ".join(sorted(self.roles))`.
`self.roles` is `roles.load(repo)`, already merged from shipped defaults and the repo's
own `.switchboard/roles.toml` / `roles/*.md` and already resident — no new read path.
Sorted for a stable prompt, because dict order is merge order and a spawn prompt that
reshuffles between runs is an unreadable diff.

Names only, no descriptions — Andrew's decision 2. `Role` has no description field, so
names-only needs no schema change, and the names are exactly the vocabulary `--role` takes.

**The newline constraint bites here and is handled by shape, not by code.** The fragment
renders as one flat clause. Six names is nothing; a repo with fifty roles would produce a
long single line, and there is no truncation. The call site says so. Not fixed today
because a limit invented before the case exists is a guess at where to cut.

### 6.4 — apply is a message, not printed output

`sb presets <name> --apply` → `Broker.apply_preset` → a row in `messages` from the caller
to the caller, `_ring(..., mode=NEXT_TURN)` putting the flattened text in the pane, then
`mark_collected` so it is not also waiting in the agent's own inbox. Printing the text
instead would have been the easy version and a different thing: command output is
something an agent read, a message is something it was told, and only the second is
durable, tagged, and visible in `sb inspect`.

No confirmation step — Andrew's decision 5 ("no. autonomous").

**The self-addressed message, which the scoping pass flagged as unexercised, was checked
rather than assumed:**

- `messages` has no constraint on `from_agent`/`to_agent`; both are plain `TEXT NOT NULL`
  with no foreign key. `to_agent == from_agent` is schema-legal.
- `store.unread_for` is a plain `to_agent=?` scan, so an unmarked row WOULD come back to
  its own sender through `sb inbox` — a second copy of a procedure it already has, and
  unread mail that `cleanup` refuses to close over. Hence `mark_collected`, the same call
  and the same reason as `_interrupt`. Pinned by
  `test_the_applied_preset_is_a_message_the_agent_sent_to_itself`.
- `store.put_message` also clears `agents.awaiting_task` for the recipient. For a
  self-message that means an agent applying a preset while still holding its placeholder
  task would be recorded as having been given work. **Left as is and stated rather than
  special-cased**: it is arguably true, and an agent with no task yet has nothing to pick a
  procedure for. Untested — this is the one behaviour of the new verb nothing pins.
- A ring that does not land leaves the row undelivered and unread on purpose, so
  `flush_pending` retries it as ordinary mail. Untested: forcing a ring failure at this
  call site needs a fake-herdr behaviour the fake does not have, and growing the fake for
  it was out of scope.

`--apply` with no name is refused (exit 2) rather than silently listing. The preset name is
resolved before the caller is, so a human who typos gets "no preset 'nope' (have: ...)"
rather than being sent to a read command that would fail too.

### 6.5 — to every role, via the protocol

Andrew overruled the scoping pass's orchestrator-only recommendation: shipping goes to all
roles. The protocol is the only text all five share, so it goes there once rather than into
five files that would drift.

**It is the DEFAULT shape, and this repo already overrides it.**
`.switchboard-shared/presets/house-rules.md` binds "commit on your own branch, never push,
PR, merge or touch main — the orchestrator integrates" to every agent here. Presets are
appended after the protocol, so the later, more specific rule wins, which is the layering
working exactly as designed rather than a contradiction: the protocol says what shipping
normally looks like, and a repo says what it looks like here. Worth knowing before reading
the new protocol sentence as an instruction to this repo's own agents — it is not one.

---

## Live proof, in an isolated clone

`git clone` of this branch into a scratch directory, driven entirely through **that
clone's own `./bin/sb`**. One real agent, `p6probe`, spawned by `sb start`.

**6.3.** Before spawning, a role that exists nowhere in the code was added to the clone as
one file, `.switchboard/roles/archaeologist.md`. The spawned agent's transcript
(`5297d226-…jsonl`) contains, in its system prompt:

    The roles that exist are: archaeologist, orchestrator, qa, researcher, reviewer, worker.

A hardcoded list passes every other check and fails this one.

**6.4.** The agent was asked to run `./bin/sb presets adversarial --apply` and report
whether the text arrived. It did, in the same session, with no `sb inbox` visit — the
transcript carries:

    [sb: from p6probe] [preset: adversarial] You applied this to your own session — it is
    part of your instructions from here on, not something to reply to. A procedure you run,
    not a mood. Use it when you are asked for an adversarial review of …

**A timing observation, recorded because the agent noticed it and it is real.** The text
did not arrive at the boundary immediately after the `--apply` call; it arrived one step
later, attached to the result of the following tool call. That is the known behaviour of
next-turn delivery (`agent prompt` queues and lands at a tool-call boundary,
`audit/phase3-delivery-primitive.md`), not something new here, and the agent's own summary
recorded "no" for the step it was asked about and "yes, one step later" for what actually
happened. Anyone specifying a procedure that must be in force *for the very next action*
should know it is in force for the one after that.

The CLI's three refusal paths were exercised by hand in the clone: `--apply` with no name
(exit 2), an unknown name (exit 1, alternatives listed), and a human applying (exit 1,
pointed at the read command).

**Teardown.** `sb cleanup`, then `sb workspace close p6probe`; the herdr workspace is gone
from `herdr workspace list`. Never an unscoped `pkill`. The clone is a scratch directory.

---

## Suite and acceptance

- **`/Users/andrew/anaconda3/bin/python -m pytest tests` — 1115 passed.** Base
  (`7847b84`, the branch point) is **1102**, measured by running the suite in the isolated
  clone at that commit rather than by memory. The 13 new: 2 for the role list, 4 for preset
  apply, 1 for `--apply` flag parsing, 6 wording containment checks. 1102 + 13 = 1115. The
  new `notify.preset` and `spawn.roles` entries went into an existing test's placeholder
  table (`test_every_spawn_prompt_placeholder_is_one_the_code_fills`) rather than adding a
  case, which is why that guard costs no count.
- **`./acceptance/accept.py phase6-prompts` — all 4 pass, first run, no re-run needed:**

      1  a cold fan-out of six starts six         PASS   6/6 took their task and reported into 6 new checkouts, 0 spawns misreported   [2m18s]
      2  a child's report wakes its parent        PASS   deferred while the parent worked, then delivered by the doorbell 70s later; the parent woke and read it   [4m09s]
      3  a block holds until the human answers    PASS   held 95s against a sibling, released by the human's answer and read it   [3m18s]
      4  a sweep names what it refused            PASS   closed 1, refused 1 and said why: 'refused sb8b57kt4-k: blocked, not finished — it has not reported an end'   [2m45s]

      all 4 pass — the fleet is sound   (4m16s)

---

## Cross-checks against what the runtime now says

Asked for explicitly, since phase 3 added three runtime messages that a prompt could
contradict. None does:

- **`[sb: from <name>]`** — the applied preset carries it, added by `broker.tag` in code
  like every other line, so a repo overriding `notify.preset` cannot drop the mark.
- **The Stop hook** (`hooks.py` `BLOCK_REASON`) names the two verbs and no reasons. The
  protocol now names six reasons and the same two verbs. Consistent.
- **The reconciler's nudge** (`prompts.toml` `notify.stalled`) — same shape, same verbs,
  and its third way out ("if you are neither, carry on") is not weakened by a longer list
  of reasons to block, because every one of them is a real stop rather than a nudge.
- **`spawn.workspace`** already tells a child sharing a checkout to re-read a file that
  changed under it. 6.6 now tells the lead to prevent that collision by assignment. The two
  face opposite directions on purpose and do not overlap.

## Unproven, and stated

1. **That agents obey any of the six.** Every wording test proves presence in the text, not
   behaviour. The prompt teaching a rule and an agent following it are different failures.
2. **`awaiting_task` on a self-message** (above) — reasoned about, not tested.
3. **A failed ring on `apply_preset`** (above) — the fallback path is not exercised, and
   was not made testable by growing the fake herdr.
4. **The role list under a large role set.** One flat clause, no truncation, six names
   proved. Where it stops being readable is unknown.

## For Andrew — one thing only he can settle

`DESIGN-TRUTH.md:142-145` lists five sanctioned reasons to block. The prompts now teach
**six**: those five, plus "an instruction is ambiguous", which he confirmed he wants kept.
The doc is therefore short by one relative to what ships. Only he edits that file, so it
was left alone; the protocol's own editing note records that the list is the thing that is
short, not the sentence.
