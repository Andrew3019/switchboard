# Audit: what in our own instruction text produces bloated human-facing output

Scope: everything that ends up in an agent's system prompt. Confirmed by reading code, not
assumed: `switchboard/broker.py:3114` builds the prompt as `protocol() + identity +
roles-list + [workspace] + role.prompt`, and `defaults/presets.toml` / this repo's own
`.switchboard-shared/presets.toml` layer preset fragments on top per role. So a
researcher/reviewer/qa spawn in this repo actually receives, in order:

1. `defaults/protocol.md` (flattened)
2. identity + roles-list fragments from `defaults/prompts.toml`
3. `[workspace]` fragment (if in a named workspace)
4. its role file (`defaults/roles/<role>.md`)
5. preset fragments bound to it: `@report-bug` (all roles) + `house-rules`
   (`.switchboard-shared/presets.toml`, all roles, this repo only) + `evidence`
   (researcher/reviewer/qa) + `verify` (qa only)

`DESIGN-TRUTH.md:137-148` is the trusted source the block/formatting wording in
`protocol.md` is drawn from — I read it, did not edit it, and it says the same thing
protocol.md says almost verbatim, so the two are not in tension.

Everything below is quoted from files as they exist in this checkout today.

## Top causes, ranked

### 1. "Restate what you were asked" is instructed independently at least seven times

- `defaults/protocol.md:184-185` (`sb done`): "what you were asked, what you found or
  did, and what it means"
- `defaults/protocol.md:212-214` (`sb block`): "write the whole thing... what you were
  asked, where you are, and those numbered questions"
- `defaults/roles/researcher.md:46`: "Restate in one line what you were asked"
- `defaults/roles/reviewer.md:61-62`: "one line restating what you were asked to review"
- `defaults/roles/qa.md:52-53`: "one line restating what you were asked to check"
- `defaults/roles/orchestrator.md:186-188`: "restate in one line what you were asked,
  then report against it"
- `defaults/roles/orchestrator.md:223-224` (block): "what you were asked, where you
  stand, and the questions..."

**Mechanism:** no single one of these is long. But the same instruction lands on an
agent from the protocol layer AND its role layer AND (for orchestrators) twice within
one role file. Repetition across independent layers of the prompt stack is itself a
signal an LLM reads as "this is the load-bearing part" — so restating the task becomes a
fixed ritual opening paragraph on every message, even to a reader (Andrew) who wrote the
task himself and, per his own complaint, doesn't need it re-explained. This is exactly
the "content that is usually dead weight" failure mode, and it is dead weight *by
design* in most cases — the protocol's own comment (`protocol.md:50-52`) defends it as
cheap insurance against a context-switched reader, but that reasoning is stated once and
then the instruction is repeated seven times as if each repetition needed its own
justification.

### 2. Ordered "say X, then Y, then Z" content checklists, with no counterweight for what to cut

- `DESIGN-TRUTH.md:140-141` / `protocol.md:211-212`: "say what you did, then what the
  result is, then any questions, numbered, each with a recommended answer"
- `defaults/roles/orchestrator.md:207-208`: "Say what you would do and the one reason
  that decides it, then what it costs if you are wrong" — three more required parts,
  every time a decision is reported
- `defaults/roles/researcher.md:46-47`: "what you found, how confident you are, and
  what it means" — three parts for what the same paragraph then calls "a line or two"
- `defaults/roles/reviewer.md:61-63`: verdict + "the two or three findings that decided
  it" — bounded, but still a fixed multi-part shape

**Mechanism:** every one of these is phrased as an inclusion list. None of them is
paired with an instruction to drop a part when it doesn't apply — nowhere does the text
say "and skip whichever of these doesn't change anything." An agent that treats the list
as a checklist (which the phrasing invites — "then... then...") produces one clause or
paragraph per item whether or not that item carries information the reader needs this
time. This is the most literal instance of the brief's failure mode #3 ("include X" with
no counterweight).

### 3. Caveat/gap-surfacing is instructed three separate times, worded as a completeness demand

- `defaults/presets/evidence.md:36-38` (bound to researcher, reviewer, qa): "If you did
  not open it, do not assert it... Distinguish what you ran from what you inferred, and
  mark anything you could not test."
- `.switchboard-shared/presets/house-rules.md:81-82` (bound to **every** role in this
  repo): "Anything you left unproven belongs in your summary. Unproven and stated is
  fine; unproven and silent is not."
- `defaults/roles/qa.md:48`: "Say what you could not test rather than leaving it to read
  as passing."

**Mechanism:** these three fire together on the same spawn for researcher/reviewer/qa
(evidence + house-rules both bind to `all`/those roles per `defaults/presets.toml` and
`.switchboard-shared/presets.toml`). Each is independently reasonable, but stacked they
say the same thing three times with three different wordings, and the house-rules
phrasing in particular ("silent is not [fine]") reads as an explicit penalty for
omission rather than for miscommunication. That is the brief's failure mode #5 almost
exactly: it rewards defensive completeness ("cover every gap I know about") over
brevity, because the visible cost of naming one more untested thing is zero and the
stated cost of not naming it is being wrong per the rule.

### 4. The instructions' own register is long, clause-stacked, and exception-laden

Example, `protocol.md:216-219` (the block paragraph, one sentence): "The `<why>` is
bookkeeping for the board and is not delivered to anyone, so putting the message in it
means nobody gets the message; a reason long enough to be the message is refused, and
shortening it is not the fix." Multiple clauses joined by "and"/"so"/qualifying asides
are the norm throughout `protocol.md` and every role file's operative paragraph (not the
HTML-comment rationale, the actual shipped text).

**Mechanism:** per the brief's failure mode #2, an LLM's continuation is primed by the
register of what it just read. An agent whose entire system prompt is several hundred
words of dense, multiply-qualified, comma-spliced prose is not primed to write two crisp
sentences — it is primed to write one more paragraph in the same voice, complete with
its own qualifying asides ("to be clear," "it's worth noting," "although..."). This is
consistent with, and probably compounds, causes 1–3: the checklist items get written out
*in* this register, not just enumerated.

### 5. The formatting rule bundles five structural devices into one instruction for what is meant to be short

`DESIGN-TRUTH.md:138-140` / `protocol.md:209-211`: "Prefer bullets, short lists and
nested lists to paragraphs, break into sections where it helps without overdoing the
spacing..."

**Mechanism:** minor next to 1–4, but real: naming five available structures (bullets,
lists, nested lists, sections, spacing-discipline) as things to reach for, with no
signal that the best answer to "make it skimmable" is often *fewer words needing no
structure at all*, nudges an agent toward visibly deploying scaffolding — a header plus
three bullets for a two-sentence answer — because using the tools it was told about
looks like compliance. This is failure mode #4 (formatting guidance that produces
structure for its own sake) at a smaller scale than 1–3.

### No direct document-vs-document contradiction found

I did not find one document telling agents to be short and another telling them to add
more, in the sense of an outright conflict (failure mode #6). `DESIGN-TRUTH.md`,
`protocol.md`, and every role file all *say* "short," "plain," "a line or two." The
bloat instead comes from those same documents' operative instructions fighting their own
stated goal (causes 1–5 above) — a softer, more pervasive problem than a contradiction,
and arguably harder to fix, because there's no single wrong sentence to delete.

## Proposed fixes

Andrew's constraint: nothing that anchors — no template, no worked example, no
word/line limit, no fixed section list. So every option below changes what an agent is
told to optimize for, not what shape to produce.

**Option A — reader-decision test.** Replace the itemized "say X, then Y, then Z"
instructions (cause 2) and the caveat-enumeration instructions (cause 3) with a single
criterion, stated once and referenced rather than repeated: for anything you're about to
write, ask whether removing it would change what the reader does next; if it would not,
cut it. This directly targets causes 2 and 3 (both are literal "include everything on
this list" instructions with no cutting rule) and indirectly starves cause 1 (restating
the task essentially never changes what the reader does next when the reader is the one
who assigned it).

**Option B — front-loaded, stoppable-read.** Tell agents to write for a reader who may
stop after the first sentence and act on it — so the decision (or the answer) has to be
fully there before anything else, and everything after is optional detail the reader is
free to not read. This reframes "concise" as a property of where the weight sits rather
than a limit on total length, so it doesn't anchor a size, but it does push against
front-loaded caveats and restatement (which delay the actual point) and against
checklist completion (once the point is made early, an agent has less reason to keep
adding parts of a template it doesn't feel it has "finished").

**Option C — deduplicate cause 1 specifically.** Say "restate what you were asked"
exactly once, in the protocol, and make it conditional there ("when the reader could not
already know it," rather than unconditionally) instead of leaving it as an unconditional
ritual repeated in five more places. This is the most surgical option: it fixes one
identified cause precisely and leaves the others untouched, so it's lower-risk but only
partial.

**Recommendation: Option A.**

The single deciding reason: it's the only option that attacks the actual thing agents
are currently optimizing for. Right now the instructions reward *checklist completion* —
did I include the restatement, the caveats, the numbered questions, the reason, the
cost-if-wrong — because that's literally what's asked for in list form, in multiple
places, and none of those lists say when to stop. Option A replaces "did I include
everything on the list" with "does this line earn its place for this reader," which
subsumes causes 1, 2, and 3 at once instead of patching each list separately (which is
what Option C does, and only for one of the three). Option B is a good pairing but is
softer — it changes emphasis, not the underlying test an agent applies line by line — so
alone it's weaker than A at stopping the checklist behavior itself.

What it costs if wrong: "does this change the reader's decision" is a judgment call, not
a rule, and judgment degrades unevenly across the fleet — `researcher.md` pins that role
to the `cheap` model tier specifically, and a weaker model asked to judge relevance is
more likely to misjudge it than to fail at following an explicit checklist. The failure
mode also flips: today's failure is over-inclusion, which is boring but safe (the reader
loses time, not information); a bad relevance judgment can under-include and silently
drop something that did matter, which is worse and quieter. If this fix ships, it's
worth someone watching whether researcher/reviewer/qa output on the cheap tier starts
omitting real caveats rather than just cutting restatement and boilerplate.
