# Phase 8, Facet 2 — runtime/state and backward-compatibility review

Reviewed: `c95d550..109bb0b` on `worker-prompt-audits-2`, runtime and state surfaces only —
model/role resolution, waiting/mail, change records and plans, identity-bound
approval/review/landing, and legacy behaviour. Nits omitted. No fixes applied: nothing in
scope was both safe and unambiguous enough for a reviewer to change on its own authority.

Facet 1's two majors (planner eval case 1/5 premise mismatch, `change.review`'s two named
writers) are not repeated here.

## Baseline

`python3 -m pytest tests/test_broker.py tests/test_models.py tests/test_roles.py
tests/test_hooks.py tests/test_status.py` — 545 passed, 101 subtests. WSL2, Python 3.11.15.
The full suite was not rerun (Phase 7 recorded 2206 passing on `dbb6479` + its test commit).

## Major 1 — inline mail has no size gate; a 78 KB payload is pasted into a pane

**Where.** `Broker._inline_mail` (`switchboard/broker.py:5883`). The only guard on the
payload is `validate.line(text, "inline mail", max_len=validate.MAX_PROMPT)`
(`broker.py:5903`) plus the implicit newline refusal.

**Why that gate cannot fire.** `limits.prompt` is 80000 and
`defaults/settings.toml` documents it as the cap for *authored config* — "Kept strictly
ABOVE `text` — authored config should never be the thing that hits a cap before a runaway
message does." `limits.text`, the cap on a message body, is 40000. So the inline gate sits
at twice the largest single message and can never reject one.

**Evidence** (probes against `tests/test_broker.py`'s fake herdr):

- one 39,000-char `sb tell` → a single `agent prompt` of **39,013 characters**, not the
  inbox notice;
- two never-rung 39,000-char messages drained by `flush_pending` → one `agent prompt` of
  **78,027 characters**.

**Reachable path and likelihood.** Any `sb tell` body or `sb done` summary up to 40000
characters, and any coalesced backlog of them. The protocol asks for a line or two and
nothing enforces it; a fan-out's burst is exactly the case the holdback gathers into one
delivery, so several long summaries arrive as one prompt.

**Impact.** The recipient's context is filled by mail it never chose to read, in one
prompt it cannot decline — the inverse of what the durable inbox exists for. Secondary:
`_confirm_rings` must then find that exact 78 KB needle in the transcript tail
(`output._carries`), and a miss routes to `_fallback_inline`, i.e. a second notice for mail
that did land. No content is lost either way — the rows stay durable and unread.

**Proportionate remediation.** One threshold of its own in `_inline_mail` — a
`limits.inline_mail` well under `limits.text` — falling back to the existing doorbell above
it. Phase 2 already specifies this ("include the tagged payload when transport and size
allow"; "Oversized ... falls back to the existing doorbell/inbox path without losing
content"). The number is the author's call, which is why it is not picked here.

## Major 2 — an unsatisfied `sb waiting` never expires, so the row can never be STALLED

**Where.** `wait_mode` is written by `store.set_wait` and cleared in exactly two places:
`Broker._ring` on a satisfying delivery (`broker.py:9017`) and `hooks.mark_turn` at
`TURN_WORKING` (`hooks.py:405`). Nothing ages it.

`status.collect` (`status.py:1390`) turns the bit into an unconditional idle excuse, and
`stalled = idle and excuse is None` — so the row is never STALLED and never reaches
`sb status --needs-me`. `hooks.stop_gate` waives the silent turn end off the same bit
(`hooks.py:451`).

**Evidence.** An idle agent with `wait_mode='background'` reads
`stalled=False, idle_excuse='waiting for background work'` at +0d, +1d, +7d and +90d.

`wait_started_at` is written by `set_wait` and surfaced by `store.wait_for`, and is **read
by nothing in the tree**. The ageing this needs was anticipated in the schema and not
wired up.

**Reachable path and likelihood.** Plain `sb waiting` has no Switchboard wake condition at
all, so only a provider-native turn can end it — and the protocol offers the verb for
exactly that. `--any`/`--all` are better off: they name children a person can see. Ending a
turn quietly without a report is the behaviour the verb invites, so an agent that reaches
for it when nothing is actually running is not an exotic case.

There is a second, unproven half. `mark_turn`'s own comment says a provider-native
background completion creates a new turn and that clearing the bit there is what stops the
wait waiving that turn's stop gate — which assumes `UserPromptSubmit` fires for such a
completion. Phase 7's live runs covered `--any` only; plain `sb waiting` was not live
verified (`notes/workflow-repair-verification.md`, "Limitations"). If that hook does not
fire, the bit survives into the next turn and waives its stop gate too.

**Impact.** The fleet's only "somebody is stuck" signal can be switched off indefinitely by
the agent itself. The board still prints the excuse text, but the row sorts as healthy.

**Proportionate remediation.** Age the excuse: `status.collect` stops honouring a wait
older than some bound, using the `wait_started_at` already stored, and the row goes STALLED
as it would have before. One comparison, no schema change.

## Minor findings (reported, not fixed)

1. **Stale payload-free-doorbell rationale, five places.** `Herdr.prompt`'s first line
   still reads "The doorbell. Carries no payload — messages live in the store"
   (`herdr.py:806`), which is now flatly false: `_ring` passes the payload through that
   exact method. `broker.py:9031` (`_deliver_interrupt`) is the load-bearing one — it
   asserts "the one ring that carries its payload is the one ring a bare `agent prompt`
   cannot be trusted with", and that every other mode is safe "because the doorbell carries
   nothing and `flush_pending` re-rings it from the store". Both are false for inline mail,
   which carries a payload through a bare `agent prompt` and is recovered by
   `_confirm_rings`/`_fallback_inline`, never by `flush_pending` (its rows are already
   marked delivered). `broker.py:8455`, `:8876` and `:8963` carry the same premise into the
   confirmation and holdback rationale. Not fixed here because restating what the holdback
   and the interrupt's uniqueness now mean is authoring, not a doc typo — and patching one
   of five would leave the set less coherent than it is.

2. **`hooks.mark_turn` writes the new `wait_*` columns before it records the turn edge.**
   `store.clear_wait` (`hooks.py:405`) is the one unguarded reader/writer of those columns;
   `hooks._explicit_wait`, `status.collect` and `store.wait_for` are all column-defensive.
   On a store where the ALTER has not run — a blocking deficit that `_reset` refused
   because agents are live — `mark_turn` raises before `set_turn`, so the activity signal
   stops being recorded for every agent rather than just the wait bit being unavailable.
   Latent, not reachable on this release's schema: all four `wait_*` columns are nullable
   and therefore addable, so `connect` migrates them in place.

3. **`human_checks: []` reads as unanswered.** `_some([])` is false, so an empty list falls
   through to `_NO_HUMAN_ANSWER` — "Not recorded — nobody has written down what a human
   still has to check". Verified against `_need_section`. Only the `"none"` string sentinel
   or a non-empty list answers §1. Either accept `[]` as the same answer as `none`, or say
   so in the guide, which currently reads as if the empty list were equivalent.

4. **`merge` now obliges nothing.** The human checklist moved to `create-pr`, which is
   right — it has to precede the PR. But a plan that names `merge` alone (the shape
   `templates/docs.json` itself had until this change) now mints one step with no approval,
   no review and no human checklist, where before it at least brought the human review.
   The guide and the template both name `create-pr` now and merging without a PR is
   incoherent anyway, so the guidance already rules it out — noting it because nothing
   warns.

5. **`create-pr`'s and `merge`'s stated requirements have no validate-time counterpart.**
   `_change_defects` checks two things (the combined approval identity at `execution`+, a
   PR at `landing`+). "Requires current verification and resolved implementation review"
   and "compares expected and current identity once" live only in the library `about`
   prose. The docstring's reason — phases are advisory and the checks are on the record's
   own claims — is coherent, so this is flagged as an explicit decision rather than an
   omission, not as a defect.

## What was checked and found sound

- **Model/role resolution.** Strict `resolve`/`get` on user input with unique
  case/punctuation variants, ambiguity refused by name, `raw:` as the only escape;
  `resolve_stored`/`get_or_fallback` on every path that reads a row already in the store
  (`restore` at `broker.py:7756`, `_state_output` at `cli.py:965`, `template_capabilities`,
  `template_ceiling`, and the codex-stickiness read in `delegate`). `RoleConfigError` and
  `ModelConfigError` are `ValueError`s and reach `cli.main`'s handler as one clean line.
  `delegate` normalises `model` to `spec.tier` before storing, which is what keeps the
  stored value resolvable later.
- **Plugin-contributed roles.** `config.roles` merges them at the right precedence without
  importing plugin code; `_role_prompt_source` resolves provenance in the same order and
  breaks a two-plugin tie the same way (alphabetically last wins).
- **Waiting state machine.** Cohorts are re-validated under the same write lock as the
  message watermark (`store.set_wait`), so a child finishing between validation and
  snapshot fails the wait rather than becoming an unobservable old result; `done` now takes
  `store.mutation` so the result row and the terminal state are one causal event. An `ask`
  or `tell` supersedes any wait; a satisfied wait skips the sibling-burst holdback; held
  rings stay owed to `flush_pending` and are not lost.
- **Inline mail, apart from size.** One unproved payload per recipient; `repair=False` so a
  payload is never blind-resent; ids marked read only on transcript proof, and
  `_fallback_inline`'s claim/open pair is atomic and correctly read back by `_last_ring`
  (the new `RING_OPEN` is newer than the `RING_FALLBACK_CLAIM` that closes the old cycle).
  Reply tracking is independent of read state, so inline delivery does not disturb it.
- **Schema compatibility.** All four `wait_*` columns are nullable, so `_deficit` classes
  them as addable and `connect` ALTERs in place; every reader outside `clear_wait` guards
  on column presence.
- **Plans store compatibility.** `kind` absent means `plan`, so no document written before
  Phase 3 is rewritten or misread; a `record` has no `steps` and `name-step` refuses it at
  the door; `_faults`/`_defective` do not report a record as incomplete; the legacy
  single-file store is still read and written unmigrated at `format` 1. A legacy plan with
  no `change` renders correctly through the human-first comment (`_NO_HUMAN_ANSWER` in §1,
  §2 and §3 omitted, the whole of the old rendering under the fold). A legacy plan whose
  `merge` obliged `merge-human-review` under the old `pre-merge` anchor does not become
  defective under the new `review` anchor — the stored edge is already in `waited`.
