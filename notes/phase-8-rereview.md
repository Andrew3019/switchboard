# Phase 8 — fresh re-review of the author repairs

Reviewed: `3a6e769` ("Resolve Phase 8 major review findings") against both facet reports —
Facet 1's two majors as restated in `.switchboard/briefs/phase-8-facet-2/brief.md`, and
`notes/phase-8-facet-2-review.md`. Reachable behaviour and composition, not the diff alone.
Nits omitted.

## Baseline

`python3 -m pytest tests/test_broker.py tests/test_status.py tests/test_config.py
tests/test_plans_evals.py tests/test_plans_plugin.py tests/test_mutation_signals.py` —
742 passed, 619 subtests, 102 s. WSL2, Python 3.11. The full suite was not rerun.

Two live probes against `tests/test_broker.py`'s fake herdr, on the burst path the cap
exists for (`_fanout` + three `done`s, drained past `RING_HOLDBACK`):

- 3 × 300-char summaries → one 965-char inline prompt carrying all three bodies;
- 3 × 3000-char summaries → the 76-char notice `[sb: from k1, k2, k3] A message could not
  be delivered inline. Run: sb inbox`, with all three rows still unread and unmodified.

So the cap is enforced on the coalesced payload and not only on a single message, and the
fallback loses nothing. That was the half of Facet 2's Major 1 the new unit test does not
cover (it tests one oversized message, not a burst that coalesces past the cap).

## Verdict on the four resolutions

| # | Repair | Verdict |
|---|--------|---------|
| 1 | case-1 shaped, case-5 viable | **not resolved** — see Major 1 |
| 2 | reviewer returns, owner records | resolved |
| 3 | `limits.inline_mail` + durable fallback | resolved |
| 4 | wait excuse ages | resolved in code; see Major 2 on authority |

## Major 1 — case 1's new brief pre-answers case 5's delta, so case 5 can no longer pass

**Where.** `defaults/plugins/plans/evals/cases/case-1-bounded-work.md`, the handed-over
brief, against `case-5-replanning.md`'s delta and its four Met conditions.

**What the repair added to case 1.** Two clauses, both inside the half that is handed to
the planner:

- "Investigate what doctor and models can truthfully establish **without invoking a
  provider command or stopping for login**";
- "the boundary between **configured, resolved and executable** are yours to reason about".

**What case 5's delta says.** Three of nine tiers resolve through `codex`; "Checking a
codex model id means invoking the codex CLI, which is slow and can stop to ask for a login
— so `sb doctor` cannot verify those three the way it verifies the rest without becoming a
command that hangs. A doctor line that reported all nine as resolved would be claiming
something it did not check for a third of them."

Two of the delta's three parts are now delivered in case 1: the provider-invocation cost is
handed over as a settled constraint, and the resolved-vs-executable over-claim is handed
over as the design question. Only the fact that three named tiers are codex-routed is new.

**Worse, the delta's premise is now false against the plan it revises.** "cannot verify
those three the way it verifies the rest" presupposes a plan that verifies the rest by
invocation. Case 1's brief forbids invoking a provider command for *any* tier, so a plan
written to it treats all nine alike and there is no "the rest" to differ from.

**Reachable path and likelihood.** Every run of the pass, on the eval suite's own ordering
(`SKILL.md`: case 5 runs last and depends on case 1's snapshot). Not intermittent.

**Impact.** A planner that correctly answers "the plan already excludes provider invocation
and the output already says configured/resolved, not executable — nothing to revise" bumps
no `tries` and reopens nothing, and scores **Not met** on two of case 5's four conditions.
Case 5 is the only replanning case in the suite, and RUBRIC.md §2 leans on it for the
proportionality contrast ("case 5 should be case 1 revised, not case 1 rebuilt"). The
repair traded Facet 1's premise mismatch (a planner obeying the direct-path rule correctly
refuses to plan case 1) for a second one a step further down the same pass.

**Proportionate repair — one clause.** Delete "without invoking a provider command or
stopping for login" from case 1's brief. The design choice the repair was for survives
intact: what "usable" means for a declared tier, and what shape says it, is still the
planner's to settle, and "the boundary between configured, resolved and executable" still
names the axis without pre-settling the provider-cost answer. Case 5 then lands its cost
claim and its per-tier asymmetry as genuinely new evidence.

The alternative, if case 1's constraint is wanted as written, is to rewrite the delta so it
does not presuppose invocation — "the plan treats all nine tiers alike, but three resolve
through `codex`, whose ids cannot be checked at all without a CLI that can hang, so
whatever the output claims for the other six it cannot claim for these three". Larger edit,
same effect. Either way the new eval test still passes
(`test_case_one_is_small_but_genuinely_shaped`): neither phrase it pins is the one that has
to go.

## Major 2 — the wait ageing is sound code that narrows a confirmed DESIGN-TRUTH line

**Authority, not correctness.** The code is right and I am not asking for it to change.

**Where.** `DESIGN-TRUTH.md:230` — "**Intentional waiting is a runtime state, not repeated
polling.** ... The stop hook and stalled detection recognize it, and only a causally
relevant event wakes it. — confirmed 2026-08-27." `status.collect`
(`switchboard/status.py:1357-1364`) now stops recognizing it after
`timeouts.wait_excuse_grace` = 4 h.

The second clause still holds — `status` mutates nothing, the wait row survives, and only
`_ring`/`mark_turn` clear it; the new test asserts exactly that. The first clause is what
becomes time-bounded, and DESIGN-TRUTH states it unbounded.

**Reachable path and likelihood.** Any `sb waiting` (plain) outstanding past four hours.
`--any`/`--all` are mostly protected by accident and worth stating: a parent whose children
are still `working` picks up the *next* excuse in the chain, `waiting on children`
(`status.py:1280`, `live_parent`), so the ageing effectively bites plain background waits
only. Overnight or long-running native background work is the realistic case.

**Impact.** Two-sided, which is why it is a decision and not a defect. Without the ageing
the fleet's only "somebody is stuck" signal can be switched off indefinitely by the agent
itself (Facet 2's Major 2, unchallenged). With it, a genuinely long background wait becomes
a false STALLED and a false `--needs-me` summons on Andrew's board. Four hours is a
defensible pick and the settings comment argues it honestly; the point is that picking it
is his call, since only he edits DESIGN-TRUTH.

**Proportionate repair.** No code change. One line to Andrew for ratification, and the
DESIGN-TRUTH entry amended to say waiting is recognized for a bounded window — sized in
`timeouts.wait_excuse_grace` — rather than indefinitely.

## Minor findings (reported, not fixed)

1. **"the single-writer rule below" points at a heading whose body is about the plan, not
   the record.** `defaults/plugins/plans/__init__.py:859` sends the reader to `WHO WRITES
   TO IT` (:884), which opens with the owner and then talks entirely about "the SHAPE of
   the plan — steps, order, owners, gates, deps" and "editing this file by hand". The
   change record's own single-writer rule is nowhere stated in its own words. The reference
   works because the heading follows the change-record section, and not because the section
   says it. Not fixed: naming the rule for the record is authoring, not a typo.
2. **`review`'s two write instructions read as opposed on a fast read.** The same `about`
   now says "Put the result in this step's `output`" and "without making the reviewer a
   second writer". Both are right — a step's own `output` is the doing agent's, like a tick
   — but the reader is not told which writer each sentence is about, and the reviewer role
   prompt (`defaults/roles/reviewer.md`) never mentions the `{commit, reviewer, findings,
   fixes}` structure at all, so the only place that asks for it is a step definition the
   reviewer may never be handed.
3. **`planner.md`'s two depth triggers both fire on the repaired case 1.** "Go deeper when
   the approach has real alternatives" is unqualified and comes first; the new sentence
   ("Where shaping was justified by a real decision but left a bounded implementation,
   write a SHORT plan") is the carve-out. It reads correctly on a careful pass — the
   alternatives here are about output semantics, not implementation approach — and case 1's
   expected signal still forbids `plan-review`. Flagged because the case it decides is the
   one the eval scores, not because the sentence is wrong.
4. **Facet 2's minors 2-5 are untouched**, which matches the brief (majors only). Worth one
   line so nobody reads this pass as having cleared them: `mark_turn`'s unguarded
   `clear_wait` before `set_turn`, `human_checks: []` reading as unanswered, `merge` alone
   obliging nothing, and `create-pr`/`merge`'s prose requirements having no validate-time
   counterpart all still stand as written.

## Reviewer-applied fix

- `notes/FEATURES.md:589` — the sixth and last site of Facet 2's minor 1. The repair
  corrected the five in `broker.py`/`herdr.py` and left the maintained feature inventory
  saying "The doorbell carries no payload — the message is in the store". Replaced with the
  inline-mail-then-notice description and the cap's name. Docs only; no test covers it.

## What was checked and found sound

- **The cap itself.** `INLINE_MAIL_MAX` gates the JOINED payload, so a coalesced burst is
  capped as a whole rather than per message (probe above). `validate.line` raises rather
  than truncating, `_inline_mail` returns `(None, [])`, and `_ring` then leaves `text` as
  the notice with `repair=True` — so oversized mail keeps the ordinary repairable doorbell
  and its rows stay unread and unmodified.
- **The confirmation needle shrank with it.** `_confirm_rings` looks for `ring["text"]` in
  the transcript tail, and `output._carries` scans the last `_ARRIVAL_RECORDS` = 50 records
  rather than a byte budget — so the needle was never truncated, but `events.payload` now
  carries at most 8 KB per `ring_sent` instead of the measured 78 KB.
- **The rewritten transport rationale is accurate.** "Repairable rings are inbox notices"
  holds exactly: notices ring with `repair=True`, inline mail and `apply_preset` both with
  `repair=False`, and `_fallback_inline` is the only path from a `repair=False` ring with
  `inline_ids` to a repairable one. `Herdr.prompt`'s new docstring promises only queueing,
  which is what it does.
- **`8000` against `40000`.** The number is under `limits.text` by 5×, so the gate can
  actually fire on a legal message — which is the whole of what was wrong with
  `MAX_PROMPT`. Nothing enforces the ordering, and nothing needs to: the settings comment
  states the intent and a repo that inverts them gets its own bug.
- **Wait ageing does not mutate.** `store.wait_for` still returns the row after the grace
  (asserted); `wait_started_at` and `wait_mode` are written together under one lock in
  `store.set_wait`, so the `wait_started is not None` guard cannot misfire on a store this
  release wrote, and on a store too old for the columns both read absent and the excuse is
  absent for the reason it always was.
- **The excuse chain's order is unchanged.** `awaiting` still wins, `live_parent` still
  follows, and an unknown `wait_mode` still yields no excuse — `.get()` and the old
  three-way chain agree on every input.
- **The stop gate was correctly left alone.** `hooks._explicit_wait` reads the same bit
  un-aged, but a prompted turn clears the wait at `mark_turn(TURN_WORKING)` before
  `stop_gate` runs, so the un-aged read is only reachable through the `UserPromptSubmit`
  gap Facet 2 already recorded as unproven. Not a new defect, and not this repair's.
- **Single-writer composition.** Nothing else in `defaults/` still tells the reviewer to
  write the change record: `create-pr.json` reads `review` from the record by identity,
  `merge.json` consumes it, and `reviewer.md` never mentions the record. `_change_defects`
  is unchanged and still checks only the approval identity and the PR, which is what its
  docstring already claimed.
- **No stale payload-free-doorbell claim survives** anywhere in `switchboard/`,
  `defaults/` or `tests/` after the fix above.
