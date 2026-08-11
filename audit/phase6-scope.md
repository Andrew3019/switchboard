# Phase 6 scope — prompts and shipping

Read-only audit. Base: `phase4-removals` tip `7847b84` (phase 3 fully merged in, phase 4's
removals landed on this branch — see its own commit "Record the phase 4 build, and mark it
done in the plan"). Phase 5 (structure) is **scoped but not built** — read from
`scope-phase5:audit/phase5-scope.md` (tip `6259680`) — so every item below states
separately whether it depends on phase 5 landing first. Modelled on `audit/phase4-scope.md`
and `audit/phase5-scope.md`. Covers BUILD-PLAN.md's phase 6 bullets 6.1–6.6.

`DESIGN-TRUTH.md` is the *source text* for this phase, not just ground truth to check
against — phase 6 is about making the shipped prompts say what it says. Everything else
(BUILD-PLAN.md's bullets, the file docstrings inside the prompts themselves) is a paraphrase
and was checked against `DESIGN-TRUTH.md` directly rather than trusted.

**Headline finding.** Five of six items are pure or near-pure wording work: the prompt
surface to edit is small and already well-organised (one protocol file, five role files, one
prompt-fragment file), and phase 4's removals already cleared the flags these prompts would
otherwise still be teaching. The two exceptions are real: **6.3** has no code path today that
could produce a role list (nothing enumerates `Role` objects into prompt text anywhere), and
**6.4** is almost entirely new code — `sb presets` has list and read today, but "apply to this
chat" doesn't exist as a verb, a delivery path, or a CLI flag. **6.1 also contains a genuine
contradiction**, not just gaps: the shipped protocol tells every agent to block on "an
instruction is ambiguous," which is nowhere in DESIGN-TRUTH's five sanctioned reasons and
sits in tension with its own "avoid blocking unless it is really needed" framing.

**Where the prompt text actually lives**, since every item below cites it repeatedly:
- `defaults/protocol.md` — the system prompt every agent gets, before role or presets.
  Flattened to one line at spawn (`config.protocol()`/`config.flatten`); a repo overrides
  the whole file via `.switchboard/protocol.md`, never merges into it.
- `defaults/roles/{orchestrator,worker,qa,researcher,reviewer}.md` — one prompt fragment per
  role, appended after protocol + identity (+ workspace).
- `defaults/prompts.toml` — `[spawn]` fragments (`identity`, `workspace`, `start_task`,
  `workspace_task`) and `[notify]` doorbell/reconciler text, filled by `Broker._say`.
- The assembly point, confirmed by reading it directly: `Broker.delegate`,
  `switchboard/broker.py:3019-3029` —
  ```
  prompts = [
      self._protocol(),
      self._say("spawn.identity", name=name, role=role, parent=me),
  ]
  if ws:
      prompts.append(self._say("spawn.workspace", workspace=ws, path=where))
  if as_prompt: prompts.append(as_prompt)
  elif r.prompt: prompts.append(r.prompt)
  prompts.extend(self._resolve_bindings(role, with_))
  ```
  This is the **one place every spawn passes through** (`sb start`, `sb workspace new`, and
  `sb delegate` all reach it — confirmed by `audit/phase5-scope.md`'s reading of `_top` and
  `_spawn_lead`), so it is also where a generated role-list fragment (6.3) would be inserted.

---

## 6.1 — the five block reasons: three missing, one contradicted

**DESIGN-TRUTH.md:142-145**, the five sanctioned reasons to block:

> Agents should avoid blocking unless it is really needed — a genuine, big,
> behaviour-changing design question; being blocked on running some command; being
> explicitly told to block; going back and forth with the agent itself; or finished work
> that needs Andrew's input or approval to complete.

**What every shipped prompt says today** — the only escalation list that exists anywhere,
`defaults/protocol.md:143-145` (identical text is this agent's own system prompt right now):

> Stop and get a human if a tool fails twice, if an instruction is ambiguous, or if you are
> about to do work you were told to delegate. Never work around a broken tool.

Three triggers, not five. Cross-checked every other shipped file for a second list and found
none — `orchestrator.md:203-207` only restates *how* to block (two-step mechanics), not *when*;
`worker.md:57-59` (the fallback every undefined role, and any role with no prompt of its own,
inherits) says only "if you need a decision that was not yours to make"; `qa.md`, `researcher.md`,
`reviewer.md` say nothing about blocking at all.

**Mapping the three against the five:**
| DESIGN-TRUTH reason | In the prompt today? |
|---|---|
| genuine, big, behaviour-changing design question | not named — "ambiguous instruction" is close in spirit but far broader |
| being blocked on running some command | approximately — "a tool fails twice," a narrower, threshold-gated version |
| being explicitly told to block | **missing** |
| going back and forth with the agent itself | **missing** |
| finished work that needs Andrew's input or approval to complete | **missing** — this is the one 6.5 needs most (a finished PR waiting on merge approval is exactly this case, and nothing today tells an agent that is grounds to block) |

That is the "three missing." The **contradiction**: "if an instruction is ambiguous" is not
one of DESIGN-TRUTH's five reasons, and it sits in direct tension with the same sentence's
own "avoid blocking unless it is really needed" — almost any task carries some ambiguity
resolvable by ordinary judgement, and DESIGN-TRUTH's own philosophy elsewhere
(`DESIGN-TRUTH.md:124-127`, "there should not be too many hard guidelines and rules... the
reconciler catching the general case is worth more than a rule for each one") argues against
a standing low-bar trigger like this. A prompt telling every agent to stop and block whenever
it meets an ambiguous instruction is teaching the opposite of "avoid blocking unless really
needed." **Confidence:** I read this as the contradiction the brief is pointing at, but it is
inference from tension between two sentences, not a case of one prompt directly citing the
other's forbidden behaviour by name — flagged as my reading, not a verbatim clash, and worth
Andrew confirming before it is treated as settled.

**Pass/fail test.** Read `defaults/protocol.md`'s escalation sentence (or its
repo-override, if one exists) and check it names, in substance, all five DESIGN-TRUTH
reasons and nothing that isn't one of them. Today: 2 of 5 present (one only approximately),
1 present that isn't on the list at all. A weak test ("the prompt mentions blocking") would
pass today and prove nothing — this only passes once the enumerated list matches.

**What changes.** `defaults/protocol.md:143-145` (the escalation sentence itself — this is
the one copy read by every agent, since role files do not repeat it). Whether to also touch
`orchestrator.md`'s block section is a judgement call: it already covers the *mechanics*
correctly and adding the *reasons* there too would duplicate protocol.md for an audience that
already gets it upstream — recommend leaving reasons in protocol.md only, mechanics
everywhere they already are.

**Code vs. wording.** Pure wording. No code reads or branches on the content of this
sentence anywhere (confirmed: `hooks.py`'s `BLOCK_REASON` and `prompts.toml`'s `notify.stalled`
are independent strings that name the two verbs, not the five reasons — see the
cross-check below).

**Cross-check against the Stop hook and the reconciler (asked for explicitly in the brief).**
Neither emits the five-reasons list, and neither needs to — both are narrower, mechanical
nudges:
- `switchboard/hooks.py:45-51`, `BLOCK_REASON` (the Stop-hook text, fired when a turn ends
  with no `sb done`/`sb block`/`sb failed`): "...call `sb done \"<summary>\"` if the work is
  finished... or `sb block \"<why>\"` if you need a human..." — names the two verbs, not the
  reasons. Consistent with the protocol, not contradicting it.
- `defaults/prompts.toml:122`, `notify.stalled` (the reconciler's nudge): "...if you are
  finished, run `sb done`... if you are stuck or need a person, run `sb block`... if you are
  neither, carry on..." — same shape, same two verbs, no reasons list. Consistent.

Neither contradicts the protocol or each other. The only defect found in this pass is the
protocol's own escalation sentence against DESIGN-TRUTH, above.

**Decision needed.** Confirm the contradiction reading above — is "ambiguous instruction" as
a block trigger meant to be removed outright, narrowed (e.g. "an ambiguous instruction *from
a human, about a genuine design fork*" — folding it into the design-question reason rather
than standing alone), or is it intentional and DESIGN-TRUTH's five-reasons list is the one
that's incomplete? Recommend narrowing it into the design-question reason: a
blanket "ambiguous → block" trigger reads as exactly the kind of standing rule DESIGN-TRUTH
argues against, and folding it removes the tension without losing the legitimate case (a
big fork disguised as an ambiguity).

---

## 6.2 — human-facing output: concise, skimmable, bulleted, sections, numbered questions

**DESIGN-TRUTH.md:135-140**:

> Human-facing output is concise, skimmable and well formatted. That covers anything an
> agent puts in front of Andrew, including what it writes before `sb block`. Prefer bullet
> points, lists, nested lists and diagrams — things that can be visually skimmed. Break into
> sections where it helps, but do not overdo the spacing. Say what you did, what the result
> is, then any questions, numbered, each with a recommended answer.

**What every shipped prompt says today.** The *numbered-questions-with-a-recommendation*
half is taught, but only for the block message specifically, in two places:
- `defaults/protocol.md:146-148`: "...write the whole thing as the last message in your own
  chat — what you were asked, where you are, and the numbered questions with a recommended
  answer — because THAT is what they read..."
- `defaults/roles/orchestrator.md:209-211`: "Write the whole thing in your own chat as your
  final message — what you were asked, where you stand, and the questions numbered with your
  recommended answer for each..."

Neither one, nor anywhere else, says **concise, skimmable, bulleted, or broken into
sections** — the formatting half of the rule is genuinely absent, confirmed by grepping every
shipped role file and `protocol.md` for "bullet," "skim," "concise," "format," "section": zero
hits outside this document. `orchestrator.md`'s "What you say" section (`:168-197`) covers
*register* (plain language, no jargon, name your reader) and *content* (synthesis, ending
with a decision) at length, but never structure. This matches the brief's "taught nowhere
today" — confirmed, not merely repeated.

**Pass/fail test.** "The prompt mentions formatting" is the weak test the brief warns
against — recommend instead a generated-text check: take a real block-chat message or `sb
done` summary an agent produced, and check it against a short mechanical rubric (has at least
one bullet or list where more than one item is being reported; questions, if any, are
numbered with a stated recommendation each; no single paragraph runs past ~5 lines without a
break). This is a check on the *artifact*, not the prompt, because the prompt teaching the
rule and an agent following it are two different failures — Andrew's own memory file
(`human-facing-output-format.md`, loaded into every one of his sessions) exists precisely
because this rule has had to be repeated by hand outside the shipped prompt.

**What changes.** `defaults/protocol.md` is the natural home — this is universal, applies to
`sb done` summaries and block-chat messages alike, and the numbered-questions half is already
there so the formatting half belongs beside it rather than in a role file only some agents
get. Secondary: `orchestrator.md`'s "What you say" section, since it is the longest existing
treatment of what a summary should look like and currently teaches register without
structure.

**Code vs. wording.** Pure wording.

**Decision needed.** None — this is closer to "write the missing sentence" than a design
question. One judgement call: whether to state the formatting rule once in `protocol.md` (my
recommendation, since DESIGN-TRUTH frames it as covering "anything an agent puts in front of
Andrew," universal) or repeat a short version in each role file's own summary guidance
(`qa.md`, `researcher.md`, `reviewer.md` already have one-line summary specs — adding
"bulleted where you're listing more than one thing" there costs little and reinforces it at
the point of use). Recommend protocol.md only, to avoid five copies drifting.

---

## 6.3 — every agent told at spawn what roles exist, generated from the roles themselves

**DESIGN-TRUTH.md:107-110**:

> The role list is lightly audited and fine as it is — as long as it is known that there are
> roles, and what roles there are. Every agent is told at spawn what roles exist, and that
> text is generated from the roles themselves, never hardcoded.

**What every shipped prompt says today.** Nothing lists the roles. `defaults/prompts.toml`'s
`[spawn]` section (`identity`, `workspace`, `start_task`, `workspace_task`) has no roles
fragment. Confirmed by grep: no shipped file contains a literal role name next to another
(no "worker, qa, researcher, reviewer, orchestrator" enumeration anywhere in `defaults/`).
`orchestrator.md:152-155` tells an orchestrator that `sb presets` exists and can be read on
demand — the closest thing to "here is a discoverable list of X" — but nothing analogous
exists for roles. This matches the brief exactly.

**Where the generated text would come from.** `switchboard/roles.py:63-70`,
`roles.load(repo)`, already returns exactly the set this needs — `dict[str, Role]`, merged
from shipped defaults plus a repo's own `.switchboard/roles.toml`/`roles/*.md` overrides
(`roles.py:11-16`'s own docstring states the layering). `Broker.__init__` already calls this
once per broker (`broker.py:498`, `self.roles = roles_mod.load(self.repo)`), so the data is
already resident by the time `delegate` assembles the spawn prompt — no new read path is
needed, only a new formatting function over data that already exists in memory at the right
moment. The insertion point is `broker.py:3019-3029` (quoted in full above): a new
`self._say("spawn.roles", roles=...)` entry between `spawn.identity` and `spawn.workspace`
would give every spawn the list without touching the CLI or the role files themselves.

**Why "never hardcoded" is a real constraint, not phrasing.** `roles.py`'s own docstring
(`:4-5`) states "Vocabulary is data (C12) — there is no closed set." A role list that names
`worker, qa, researcher, reviewer, orchestrator` as a literal string in `prompts.toml` (the
way `identity`/`workspace` name their placeholders but not role names) would go stale the
moment a repo defines its own role in `.switchboard/roles/*.md` — exactly the case
`roles.get()` (`roles.py:73-84`) already exists to support. The generated text has to read
`self.roles.keys()` (or the merged dict `roles.load(repo)` returns) at spawn time, per repo,
not ship as a static sentence.

**Pass/fail test.** Not "the prompt mentions roles" — instead: add a role via
`.switchboard/roles/newrole.md` in a test repo, spawn any agent, and check its system prompt
names `newrole` without any code or prompt-text change beyond the new file. Today this fails
unconditionally, since no fragment exists to fail correctly or incorrectly — there is nothing
to generate from the roles yet.

**What changes.** `defaults/prompts.toml` (a new `[spawn]` entry, e.g. `roles`, with a
`{roles}` placeholder — the docstring at the top of the file already documents the
placeholder-substitution convention this would follow), `switchboard/broker.py:3019-3029`
(build the `{roles}` string from `self.roles` and pass it to a new `self._say("spawn.roles",
...)` call), and nothing in the five role `.md` files — this is spawn-fragment work, not
role-prompt work, so it does not collide with 6.1/6.2's edits to the same files.

**Code vs. wording.** Mostly code. The wording is one new template string (a sentence plus a
`{roles}` placeholder); the substance is a formatting function that turns `dict[str, Role]`
into a flat, single-line, human-readable list and a one-line call site change in `delegate`.
Smaller than 6.4, but genuinely code, not a prompt edit.

**Depends on phase 5?** No direct dependency found. 5.3 (bare-agent delegate refusal) is
flagged in `scope-phase5:audit/phase5-scope.md` (its own "Collisions with phase 6" section)
as wanting a `Role.can_delegate` field that 6.3's generator "should read... when explaining to
a spawned worker why it can't delegate" — that is a *nice-to-have* alignment, not a
dependency: 6.3 can ship a role list with no capability annotation today, and gain a
"(can delegate)" / "(cannot delegate)" marker per role later if 5.3 lands the field first.
Recommend building 6.3's generator now, and revisiting once 5.3 exists, rather than blocking
6.3 on an unbuilt phase-5 item.

**Decision needed.** What the generated text says about each role — just names, or names
plus a one-line description? `Role` (`roles.py:36-41`) carries no description field today,
only `name`, `model` (tier), `prompt`. A names-only list ("roles available: orchestrator,
worker, qa, researcher, reviewer") needs no schema change. A names-plus-description list
needs a new `Role` field, sourced from... where — the file's own frontmatter (today only
`model` lives there, e.g. `orchestrator.md:2`, `+++\nmodel = "default"\n+++`) or a fixed
first line of the prompt body? Recommend names-only for the first cut: it satisfies "known
that there are roles, and what roles there are" literally, costs no schema change, and a
description field can follow once it's clear agents actually need it to pick correctly.

---

## 6.4 — `sb presets` gains list / read / apply-to-this-chat

**DESIGN-TRUTH.md:292-295**:

> `sb presets` needs a parameter to list, and one to apply the prompt to the current chat or
> just read it. Picking a preset should inject a prompt: sb pastes it in, the same path as
> any other message. This must be known to all sessions.

**What exists today, confirmed by reading the code.** List and read both already exist:
`switchboard/cli.py:209-210` registers `sb presets [name]` — no name lists, a name prints
that one preset's text — dispatched at `cli.py:898-920`
(`presets_mod.text(b.repo, args.name)` for read, `presets_mod.available(b.repo)` +
`presets_mod.bindings(b.repo)` for list). **Apply-to-this-chat does not exist in any form** —
no third CLI branch, no flag, no broker method. This narrows DESIGN-TRUTH's "needs a
parameter to list, and one to apply... or just read it" to one missing piece, not three: list
and read are done, only "apply" is unbuilt.

**The mechanism to reuse already exists, for a different verb.** "sb pastes it in, the same
path as any other message" describes exactly what `Broker._interrupt`
(`switchboard/broker.py:3786-3829`, used by `sb tell --interrupt`) already does: it sends an
escape keypress (`self.h.send_keys(name, "esc")`), writes a message row, and delivers it
through `self._ring(name, body, mode=INTERRUPT)` — landing the text in the target's pane the
same way a human's typed message would. `apply-to-this-chat` needs the same delivery
mechanism aimed at the **caller's own name** rather than another agent's, which is a new
code path (self-targeted delivery is not something `tell` supports today — `tell` refuses
`HUMAN` as a target, `broker.py:3251-3257`, but nothing in it special-cases "message to
yourself" either way, so this is unexercised territory, not a guarded-against case).

**Only orchestrators are told presets exist at all**, confirmed by grep across every shipped
prompt file:
- `defaults/roles/orchestrator.md:152-155` — the only place `sb presets` is named as a
  command an agent can run.
- `defaults/roles/qa.md:9-10` — mentions preset *bindings* (`verify`, `evidence`) exist for
  qa agents, but never tells the agent it can run `sb presets` itself to read one on demand.
- `defaults/roles/worker.md:13-14` — mentions presets only as a stage in the spawn-assembly
  order ("protocol → identity → workspace → ROLE → presets"), not as a command.
- `qa.md`, `researcher.md`, `reviewer.md`, `defaults/protocol.md` — no mention of `sb
  presets` as a runnable verb anywhere.

DESIGN-TRUTH's "This must be known to all sessions" is therefore two separate gaps, not one:
the apply verb doesn't exist in code, and even the parts that do exist (list, read) are
taught to one role out of five.

**Pass/fail test.** Code: `sb presets <name> --apply` (or equivalent) pastes the named
preset's flattened text into the calling agent's own current turn and it is visibly present
in the transcript — today this fails, the flag does not parse. Prompt: any shipped role
prompt, asked "how would you read a named procedure without being told it up front,"
answers with `sb presets` — today this passes only for `orchestrator.md`.

**What changes.** This is genuinely split:
- **Code**: `switchboard/cli.py:209-226` (new flag on the `presets` subcommand, e.g.
  `--apply`), `switchboard/cli.py:898-920` (a third dispatch branch), a new
  `Broker` method (or a reuse of `_interrupt`'s delivery internals refactored to accept a
  self-target) in `switchboard/broker.py`, and `switchboard/presets.py:92-110`
  (`text()` already returns the flattened body this would deliver — no change needed there,
  it's the delivery side that's new).
- **Wording**: `defaults/protocol.md` (if "known to all sessions" means universal — every
  role, not just orchestrators, since DESIGN-TRUTH's phrase reads as unqualified) or, more
  narrowly, each of the four role files that currently say nothing about presets at all.

**Code vs. wording.** Mostly code, more so than 6.3 — 6.3 reuses an existing data source and
adds one formatting call; 6.4's apply verb has no existing broker method to extend and needs
a new CLI flag, a new dispatch branch, and a new (or adapted) delivery path. The prompt change
is the smaller half of this item by a wide margin.

**Decision needed.**
1. **Does "known to all sessions" mean the wording change belongs in `protocol.md`
   (universal) or in each role file individually?** Recommend `protocol.md` — presets are
   framed in `presets.py`'s own docstring (`:12-13`) as "what SOME agents need," but *knowing
   the verb exists* is cheap and universal even when a given agent's repo has bound it
   nothing; the alternative (five near-identical one-liners) is the same duplication cost
   6.1 already avoids by centralising.
2. **What should `--apply` actually be named, and should it require confirmation before
   pasting into the current turn?** Not scoped here — a genuine design question for whoever
   builds it, since `_interrupt`'s existing self-target-adjacent behaviour (cancel + paste)
   is more disruptive than "read a procedure," and applying to *your own* current turn is a
   new kind of self-message with no precedent in the store schema (`to_agent == from_agent`
   is not a case any existing query or constraint has been checked against — worth a builder
   confirming `store.put_message`/`store.unread_for` behave sanely for it before assuming
   the reuse is free).

---

## 6.5 — shipping: branch, push, PR, URL in summary; merge needs explicit approval

**DESIGN-TRUTH.md:281-284**:

> Who merges depends, but merging needs explicit approval from Andrew. A prompt rule for
> now: do not merge without asking first. The default shape of shipping work is branch named
> for the workspace, push, open the PR, and put its URL in the summary.

**What every shipped prompt says today: nothing.** Confirmed by grepping every shipped
prompt file and `protocol.md` for "push," "PR," "pull request," "merge," and "branch named"
— the only hit in the entire `defaults/` tree is `reviewer.md:21`'s "Some thoughts on this
PR," which is an example of a bad review opening, not an instruction about shipping. No
prompt tells an agent to push, to open a PR, to put its URL in a summary, or that merging
needs approval. This matches the brief's "None of this is in any prompt" exactly — it is not
merely thin, it is entirely absent.

**Also checked and worth stating plainly: no prompt says the opposite either.** There is no
existing "merge freely" or "merge when done" instruction to remove — this item is pure
addition, not addition-plus-correction the way 6.1 is.

**Pass/fail test.** Behavioural, not "the prompt mentions shipping": an agent whose task
implies shipping code (a workspace lead finishing implementation work) produces, by the time
it reports done or blocks, (a) a branch named for its workspace, (b) that branch pushed, (c)
an open PR, (d) the PR's URL present in its `sb done` summary or block-chat message, and (e)
no merge command run without Andrew's prior explicit go-ahead recorded in the chat. Today: no
prompt establishes any of (a)-(e), so nothing in an agent's behaviour can be checked against
a rule that doesn't exist yet — this is greenfield, not a partial pass.

**What changes.** `defaults/roles/orchestrator.md` is the natural, and probably sufficient,
home: DESIGN-TRUTH's CUJ text (`:69-78`) already assigns "a lead cleans up its children,
pushes the PR if relevant, and summarizes" and "a bare agent under the top pushes and opens
its own PR" to orchestrators and bare agents specifically — this is shipping-role behaviour,
not something every reviewer or researcher needs told, since those roles do not typically
finish a piece of work end to end. Recommend adding a "## Shipping" section to
`orchestrator.md` alongside "## Close what is finished," and a short addition to
`worker.md`/protocol.md's fallback for the bare-agent case DESIGN-TRUTH names explicitly
("a bare agent under the top pushes and opens its own PR"). **Given 6.1's finding that
"finished work needing approval" is a missing block reason**, this item and 6.1 share one
sentence: the natural place to say "do not merge without asking" is right where the block
reason for it gets added — a single edit could add "finished work waiting on a merge is
exactly the case above" rather than writing the merge-approval rule and the block-reason
fix separately in two files.

**Code vs. wording.** Pure wording, and DESIGN-TRUTH says so explicitly — "a prompt rule for
now, no merge verb." No new CLI command, no new broker method; `sb` already has no `merge`
verb to remove or guard (confirmed: grep of `cli.py` for `"merge"` returns nothing outside
comments), so there is nothing in code that could accidentally let an agent merge —
the enforcement is entirely social/prompt-level by design, matching BUILD-PLAN.md's own
phrasing.

**Depends on phase 5?** No. This is independent of the top/workspace stamp (5.1/5.2) and the
tree-boundary work (5.4) — shipping behaviour is the same regardless of how a workspace was
created or whether cross-tree visibility is locked down yet.

**Decision needed.** None structurally — this is "write the missing rule," not a design
question. One judgement call, flagged for Andrew rather than assumed: should the shipping
section live only in `orchestrator.md` (my recommendation, since DESIGN-TRUTH's own CUJ
text ties pushing/PR-opening to leads and bare agents specifically) or also get a short
mention in `protocol.md` so it's universal the way 6.1's block reasons and 6.2's formatting
rule are? Recommend orchestrator.md + a one-line pointer in the bare-agent fallback
(`protocol.md`, since `worker.md` was deleted and undefined/bare roles inherit the protocol
directly per `protocol.md:19-27`'s own docstring) — not a full universal rule, since
qa/researcher/reviewer roles do not ship code as part of their normal job.

---

## 6.6 — a lead assigns disjoint files and serialises overlap

**DESIGN-TRUTH.md:161-162**:

> A lead's children share its worktree, so the lead assigns disjoint files and serialises
> anything that overlaps.

**What every shipped prompt says today — half of this is already there.**
`defaults/roles/orchestrator.md:134` ("Plan, then re-plan" section): "Serialise anything that
writes the same files, because parallel writers conflict and you will pay for it in merges."
This covers the *serialise-overlap* clause correctly and completely.

**What's missing: the *assign-disjoint* clause, and the *why*.** Nothing in `orchestrator.md`
instructs a lead to partition file ownership across children up front — the existing text
only says what to do once an overlap is noticed (serialise it), not how to avoid noticing one
in the first place by assigning non-overlapping scopes at split time. The **reason**
("children share its worktree") is also absent from `orchestrator.md`'s own text — it appears
only in the child-facing direction, in `defaults/prompts.toml:39-44`'s `spawn.workspace`
fragment ("Other agents and the human may be in this same workspace at the same time... If a
file has changed under you since you read it, re-read it before you edit"), which teaches a
*child* to defend against a stale read, not a *lead* to prevent the collision by construction.
Confirmed by re-reading the full "Plan, then re-plan" section (`orchestrator.md:129-137`):
it discusses independence, sequencing, and serialising overlap, but never "give this child
these files and that child those files" as an explicit assignment step.

**Pass/fail test.** Not "the prompt mentions files" — `orchestrator.md` already does, for the
overlap half. Instead: does the plan-section text instruct the lead to state, at split time,
which files each child owns, before any child starts writing? Today: fails for that specific
instruction, though the adjacent (and necessary, but insufficient alone) serialise-on-overlap
rule already passes.

**What changes.** `defaults/roles/orchestrator.md:129-137` (the "Plan, then re-plan"
section) — one or two added sentences: assign disjoint files as part of the split, stated
alongside the existing serialise-overlap sentence, plus the "because you share a worktree"
reason so the rule reads as caused rather than arbitrary.

**Code vs. wording.** Pure wording. Nothing in code enforces or could enforce file
ownership across sibling agents sharing one worktree — there is no lock, no claim, no
per-file assignment record anywhere in `store.py` or `broker.py` (confirmed: grepped for
any "file lock"/"file claim"/"owns file" concept, found none) — this is entirely a
discipline the lead is trusted to apply, same as the rest of the "Plan, then re-plan"
section already is.

**Depends on phase 5?** No. This is scoped to the fact "a lead's children share its
worktree," which is already true today and unaffected by 5.1/5.2's top-vs-workspace stamp —
a workspace lead's children shared its worktree before phase 5 and will continue to
afterward; phase 5 changes *who becomes a lead in the first place* (5.3's bare-agent
refusal), not what a lead does once it is one.

**Decision needed.** None — this is a small, additive wording fix to a section that already
gets most of the rule right.

---

## Sequencing

**Within phase 6, all six items touch largely disjoint text** and can be built in any order
or split across owners, with two exceptions:
- **6.1 and 6.5 share one sentence's neighbourhood** — 6.1 adds "finished work needing
  approval" as a block reason, 6.5 adds the merge-approval rule that reason exists to serve.
  One owner, one pass over `protocol.md`'s escalation sentence and `orchestrator.md`'s
  shipping section together, so the two don't independently invent slightly different
  phrasings for "you finished, but it needs Andrew's OK" (the failure mode
  `audit/phase4-scope.md` already flagged for 4.2-vs-6.1 on the five role files).
- **6.3 touches `broker.py:3019-3029` and `prompts.toml`; 6.4 touches `cli.py` and
  `broker.py`'s delivery internals.** Disjoint lines, but both are net-new code in the same
  two modules (`broker.py`, `cli.py`) in the same release window — sequence as separate
  commits, same reasoning `audit/phase4-scope.md` gave for its own `cli.py`/`broker.py`
  overlap with the in-flight `tell-modes` work.

**Against phase 5, item by item** (the brief's specific ask):
- **6.1, 6.2, 6.5, 6.6** — no dependency. All four are either universal (protocol.md) or
  scoped to facts already true today (a lead's children already share its worktree; a
  finished PR already needs approval regardless of how the workspace was created).
- **6.3** — no dependency for the base case (a flat role-name list), a *soft* one for the
  enriched case: `scope-phase5:audit/phase5-scope.md`'s "Collisions with phase 6" section
  already names this — if 5.3 adds `Role.can_delegate`, 6.3's generator should read the same
  field rather than the two drifting apart. Not a blocker; build 6.3 now, extend later.
- **6.4** — no dependency. Presets apply-to-chat is orthogonal to top/workspace stamping and
  tree-boundary scoping.
- **None of the six depend on 5.1/5.2/5.4 specifically** (the stamp, the delegate branching,
  the tree-boundary scoping) — BUILD-PLAN.md's stated reason for phase 5 before 6
  ("the prompt should explain a rule the code already enforces") applies most directly to
  `orchestrator.md`'s existing top/workspace framing paragraph (already flagged by
  `scope-phase5`'s own document, not part of this phase's six items) rather than to any of
  6.1-6.6, which describe rules independent of that split. Worth Andrew knowing this phase
  does not actually need to wait on phase 5 landing, contrary to BUILD-PLAN's blanket
  ordering note — though building phase 5 first still avoids a second pass over the same
  files phase 5's own document already flags for `orchestrator.md`.

---

## The two constraints, and where they bite

**No agent argument may contain a newline; prompts are delivered joined into one
`--append-system-prompt`.** Both already shape every item here, not just the new ones:
- Every addition proposed above (6.1's rewritten escalation sentence, 6.2's formatting rule,
  6.3's generated role list, 6.5's shipping section) must be written wrapped for humans and
  flattened to one line at send time — `defaults/protocol.md:10-13`'s own docstring states
  this is why ORDER is the only structure that survives ("nothing here may depend on layout,
  on a heading, or on being an item in a list"). A bulleted list *taught* by the prompt
  (6.2) is not the same as the prompt itself *being* bulleted — the prompt has to describe
  bullets in prose, since it cannot use them.
- **6.3's generated role list is the one item where this genuinely bites, not just
  stylistically.** A role list has to render as a single flat clause (e.g. "roles available:
  orchestrator, worker, qa, researcher, reviewer" or a repo's own set) — no line breaks
  between names, which is easy for a short list and would need explicit truncation or
  summarisation handling if a repo ever defined enough custom roles to make one line
  unwieldy. Not a problem today (five names), worth a comment at the call site for whoever
  builds it.
- **6.4's apply-to-chat text is pasted as a message, not appended as a system prompt** — the
  newline constraint still applies (herdr rejects it in *any* agent argument, not just spawn
  ones, per `protocol.md:10-11`'s framing), so a preset file's multi-line source
  (`presets.py:86`, `flatten()`) already handles this for read/list; apply needs to reuse the
  same flattening, not reinvent it.

---

## Decisions needed from Andrew — collected

1. **6.1** — is "block on an ambiguous instruction" meant to be removed, or narrowed into
   the design-question reason? Recommend narrowing it in.
2. **6.2** — state the formatting rule once in `protocol.md`, or repeat a short version in
   each role file's summary guidance too? Recommend `protocol.md` only.
3. **6.3** — role list as names only, or names plus a description? Recommend names only for
   the first cut; no schema change needed either way for names-only.
4. **6.4** — should the wording change ("presets exist, and can be applied") go in
   `protocol.md` (universal) or stay orchestrator-only? Recommend `protocol.md`. Separately,
   a genuinely open design question for whoever builds `--apply`: what to name the flag and
   whether pasting into the current turn needs any confirmation step, given no code path
   handles a self-addressed message today.
5. **6.5** — shipping section in `orchestrator.md` alone, or also a universal one-line
   pointer in `protocol.md`'s bare-agent fallback? Recommend both: orchestrator.md for the
   substance, one line in protocol.md for the bare-agent-ships-its-own-PR case DESIGN-TRUTH
   names explicitly.

---

## What surprised me

- **The contradiction in 6.1 is not where I expected to find it.** I went in looking for a
  prompt that *permits* something DESIGN-TRUTH's rejected list forbids (the phase-4 shape of
  defect). What's actually there is subtler: a legitimately-intended escalation trigger
  ("ambiguous instruction") that isn't wrong on its own, but sits in tension with the same
  paragraph's framing once measured against DESIGN-TRUTH's actual five-item list — a
  contradiction of *scope*, not of *permission*.
- **6.3 and 6.4 both looked, from the brief alone, like they might be pure prompt work with
  a code footnote.** Reading the code first changed that: 6.3 has no producer for the data
  it needs to teach (not even a stale one to fix — it doesn't exist), and 6.4's "apply"
  verb has no partial implementation to extend, only a superficially-similar mechanism
  (`_interrupt`) built for a different purpose (cross-agent, not self-targeted) that would
  need real adaptation, not reuse as-is.
- **6.6 is smaller than the brief's framing suggested.** "A lead assigns disjoint files and
  serialises overlap" reads as one rule; the code already states half of it correctly
  (serialise-on-overlap), and the missing half is a short, low-risk addition rather than new
  ground — closer to phase 3's "already half-fixed" pattern than phase 4's "ground-up" one.
- **Nothing in this phase actually needs phase 5 to land first**, despite BUILD-PLAN's
  blanket "phase 5 before 6" note — every one of the six items is either universal or scoped
  to a fact (shared worktree, finished-PR-needs-approval, roles-are-data) that holds
  regardless of whether the top/workspace stamp exists yet. Worth flagging the same way
  `audit/phase4-scope.md` flagged phase 3's "before" rule not actually gating phase 4's
  items — a stated ordering rule that turns out to be about file-touch coordination, not a
  real dependency, once each item is read individually.
