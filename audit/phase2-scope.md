# Phase 2 scope — the human path

Read-only audit. Base: `main` (`19fc485`), this branch adds nothing but this file. Ten
items: BUILD-PLAN.md's 2.1–2.6, plus four things phase 1 found and left (labelled A–D
below, in the order the brief gave them). Every file:line was re-read in the current
tree; BUILD-PLAN.md was written 2026-08-09 22:06 and two commits already on this branch
landed after it (`0f69733` 22:33, `2fce8cc` 2026-08-10 02:33) and change the picture for
2.1 and 2.2/B, so treat BUILD-PLAN's own line numbers and some of its verdicts as stale —
this document supersedes it for phase 2.

---

## 2.1 — the `why` is bookkeeping, not the message

**What happens today.** Already substantially fixed, in `0f69733` (landed 27 minutes
after BUILD-PLAN.md's own timestamp). `sb block`'s help text
(`switchboard/cli.py:168-174`) now reads "ONE short line for the board; write the full
question in your own chat, which is what the human reads." `validate.reason`
(`switchboard/validate.py:127-162`) rejects a `why` with a newline or over 200 chars
(`defaults/settings.toml`, `limits.block_reason`), and the refusal message itself repeats
the two-step instruction instead of teaching the flattening workaround BUILD-PLAN.md
warned about. Every shipped prompt agrees: `defaults/protocol.md:140-147`,
`defaults/roles/orchestrator.md`, `defaults/roles/worker.md` all say chat first, one line
second, `why` is bookkeeping. Two tests pin this:
`tests/test_roles.py::test_every_shipped_prompt_that_mentions_blocking_says_where_the_message_goes`
and `test_no_shipped_prompt_tells_an_agent_to_put_the_message_in_the_reason`.

The "why is shown to Andrew in six places" half is now **five**, not six — the sixth
(herdr's own state message) was removed as a side effect of `2fce8cc` (see 2.2/B), not as
a targeted fix for this item. The five that remain: `board.py:189-201` (board row),
`status.py:1130-1136` (NEEDS YOU), `status.py:1358-1359` (`sb inspect` detail),
`status.py:219,332-336` (`blocked_why` in `--json` output, both `status --json` and
`inspect --json`), `broker.py:4151-4155` (`_surface`, a desktop notification).

**Pass/fail test.** Block an agent with a >200-char or newline-containing reason: `sb
block` must refuse before the block is recorded (fail = it silently truncates or stores
it). Then block with a short reason and confirm the board row and `sb status
--needs-me` both show that short reason, unlabelled as anything but a board tag — this
is expected behaviour now, not a bug.

**What a fix would touch.** Nothing, in my judgement — see the judgement-call section
below. If Andrew disagrees and wants the five remaining surfaces suppressed or relabelled
anyway: `board.py:189` (`note()`), `status.py:1117-1165` (`_attention`), `status.py:1345+`
(`render_detail`), `status.py:200-336` (`AgentStatus.as_dict`), `broker.py:3296-3342` /
`4151-4155` (`block`/`_surface`).

**Size.** Small if pursued at all; possibly zero work — see judgement call.

---

## 2.2 — typing into the pane must clear the block

**What happens today.** Still live, unchanged by the recent commits. The only thing that
clears a blocked row is `_unblock_if_needed` (`broker.py:4126-4149`), called from exactly
one place — `_ring` at `broker.py:4024-4025`, `if answer: self._unblock_if_needed(who)` —
and `answer` is only ever `True` from `Broker.tell()` when `me == HUMAN`
(`broker.py:3132-3135`). There is no `sb unblock` verb and nothing observes pane input;
the agent process itself does see text typed into its own pane (that is herdr's pane, not
switchboard's), so from the agent's point of view the question is answered, but the store
row (`agents.state = "blocked"`) never moves. It stays on `sb status --needs-me` /
NEEDS YOU forever and its mail keeps being held (`_ring`'s blocked-check,
`broker.py:4016-4020`).

**This is the same gap as phase-1 leftover B** — see that item below; the brief asked me
to say which, and it is not a different bug, just the same one named twice. I treat them
as one item from here on (**2.2/B**).

Distinct from this: the collateral damage phase-1 item 1.9 found (a sibling's ordinary
mail silently clearing a block, `block()` pushing herdr `IDLE` and costing the name) is
now fixed, in `2fce8cc` — `block()` no longer calls `_push_state` at all, and
`flush_pending`/`_ring` explicitly hold a blocked agent's mail
(`broker.py:3901-3906`, `4016-4020`) rather than unblocking it on delivery. So a fix for
2.2/B no longer has to untangle that; it only has to add a genuine "the human answered"
signal that isn't `sb tell`.

**Pass/fail test.** Block an agent, then type a reply directly into its pane (not `sb
tell`). Pass = the agent's row leaves NEEDS YOU / `sb status --needs-me` and its held
mail flushes. Today this fails: the row never leaves.

**What a fix would touch.** `Broker.tell()`/`_unblock_if_needed`
(`broker.py:3093-3135`, `4126-4149`) for a new self-clear path — most plausibly a new
verb the agent calls itself once it notices the reply on its own next turn, rather than
switchboard trying to detect raw pane input (there is no existing pane-content-diff
mechanism to reuse; herdr's `at_prompt` detector is unrelated). That means a new `cli.py`
subcommand and prompt text teaching agents to call it
(`defaults/protocol.md`, role prompts).

**Size.** Medium — needs a design decision (new verb vs. some other signal) as well as
the mechanical change, and prompt updates that must stay consistent with 2.1's already-
shipped chat-first text.

---

## 2.3 — a top-level agent's `done` reaches nobody

**What happens today.** Unchanged, and by design rather than oversight.
`Broker.done()` (`broker.py:3255-3294`): a `done` message to the parent is written only
`if parent` (3280-3282), and the doorbell poke is gated the same way (3290-3293,
`if parent: self._ring(parent, ...)`). For a root agent both are skipped. `_push_state`
(3284) only ever touches herdr's board/status columns, never `h.notify` — `_surface`
(`broker.py:4151-4155`, the only caller of `h.notify`) is called solely from `block()`,
never from `done()`. `AgentStatus.needs_human` (`status.py:286-299`) is built from
`blocked`/`at_prompt`/`stalled`/`waiting_to_be_rung`/`unread` — a `done` state satisfies
none of them, so a finished top never appears in NEEDS YOU or gets a notification. The
docstring at `broker.py:3256-3262` states the reasoning explicitly: a root's summary "is
not mail — it is a record," on the view that a mailbox nobody reads is a second copy of
what the board already shows.

**Pass/fail test.** Have a root/top-level agent (no parent) call `sb done`. Pass = Andrew
gets some signal — notification, NEEDS YOU entry, or equivalent — without having to
notice a plain `done` row himself. Today this fails: nothing distinguishes it from any
other row on the board.

**What a fix would touch.** `Broker.done()` (`broker.py:3255-3294`), adding a
`_surface()` call or a `needs_human`-visible flag specifically for the `not parent` case;
possibly `AgentStatus.needs_human` (`status.py:286-299`) if the fix should also list it
under NEEDS YOU rather than just notify.

**Size.** Small-medium — needs a decision on which surfacing mechanism (notification vs.
board flag vs. both), otherwise a narrow, single-function change.

---

## 2.4 — `sb inspect` should show ~100 lines, not 40

**What happens today.** Confirmed still 40: `defaults/settings.toml:355`,
`output_lines = 40`, fanned out into three module constants that all derive from the
same config key — `switchboard/output.py:50` (`DEFAULT_LINES`), `switchboard/status.py:1223`
(`DEFAULT_LINES`, used by `cli.py:311`'s `-n` default), and `switchboard/herdr.py:74`
(`READ_LINES`). No other logic depends on the literal value.

**Pass/fail test.** Run `sb inspect <name>` with no `-n` on a transcript longer than 40
lines. Pass = ~100 lines of tail shown; fail = still 40.

**What a fix would touch.** `defaults/settings.toml:355` only — a one-line config bump.
Everything downstream already reads from this key.

**Size.** Tiny.

---

## 2.5 — board click lands on the wrong agent

**What happens today.** Confirmed still live, same mechanism BUILD-PLAN.md names.
`_visible_len` (`switchboard/board.py:331-332`) strips ANSI colour codes and then takes
`len()` — a character count, blind to wide characters (CJK, most emoji, 2 columns each)
and zero-width ones. It backs `_fit` (`board.py:335-344`), the sole function guaranteeing
"a line occupies one terminal row" (its own docstring at 336, and the invariant comment
at 311-313 names the exact failure: a wrapped line pushes every row below it down by one,
and the next click focuses the wrong agent, looking exactly like a correct one). Click
dispatch (`board.py:525-534`, specifically `agent_at(rows, ev["row"])` at 526) maps the
terminal's own reported row — which the real terminal wraps, since `_visible_len`
undercounted — straight into the pre-wrap `rows` index (`agent_at`, `board.py:317-328`).
The width itself (`_size()`, `board.py:425-426`) is correctly in terminal columns; only
`_visible_len`'s notion of how many columns a string occupies is wrong.

**Pass/fail test.** Put an agent name or note containing one wide character (e.g. an
emoji or CJK character) on the board with other agents below it in a narrow-ish pane;
click a row below it. Pass = the correct agent's row is focused; fail = a different one
is (or the pane visibly shows a wrapped line at all, which is the same bug by the
invariant's own definition).

**What a fix would touch.** `board.py:331-332` (`_visible_len`, needs real display-width
math — e.g. `wcwidth` or `unicodedata.east_asian_width`, no such handling exists
anywhere in the file today), and `board.py:335-344` (`_fit`'s truncation, `[:width]` at
344, which slices by character and would need to become column-aware too so it doesn't
cut a wide character in half). `agent_at`/click dispatch need no change — they're correct
given the invariant; the bug is entirely upstream of them.

**Size.** Small — contained to two functions in one file, but may need a new dependency
(`wcwidth`) or a hand-rolled width table, and touches `tests/test_board.py` if it exists.

---

## 2.6 — `sb status` still pointed at Andrew in four places

**What happens today.** Confirmed — four current live places present `sb status` as
Andrew's own surface, contradicting `DESIGN-TRUTH.md:230` ("`sb status` is not for
Andrew — only `sb board` is"):

1. `cli.py:833-838` — the human branch of `sb inbox` tells Andrew directly: "...a block
   waits for you in `sb status --needs-me`".
2. `status.py:1125-1131` — `sb status`'s own NEEDS YOU section, whose comment says "This
   IS the human's inbox."
3. `cli.py:184` — `sb status --mine`'s help text: "(for a human: every agent)".
4. `cli.py:866` — `sb block`'s confirmation message to the *blocking agent* still cites
   `sb status --needs-me` as where "they" (the human) will look. This one has already
   been partly reworded as a side effect of 2.1's fix (it no longer implies the human
   reads the `why` in full) but still names `sb status` as the human's tracking surface.

Agent-facing uses of `sb status` (told to agents about their own children/cohort, e.g.
`defaults/protocol.md:135`, `orchestrator.md:60,178`, and the `sb board` refusal at
`cli.py:722` shown only when `me != HUMAN`) are correct as-is and out of scope here.

**Pass/fail test.** `sb inbox` (as the human), `sb status --help`, and `sb block`'s own
confirmation output must not name `sb status` as where Andrew looks; they should point at
`sb board` instead. Fail = any of the four still does (grep the four locations above for
`sb status`).

**What a fix would touch.** `cli.py:833-838`, `cli.py:184`, `cli.py:866` (reword three
messages), and `status.py:1125-1131` (either strip the human-facing framing or move it).
The 2.4-2.6 investigation flagged a real coupling here: the board currently has **no**
NEEDS YOU equivalent at all (confirmed: no such string anywhere in `board.py`), so
rewording `sb status`/`sb inbox` to point at `sb board` without first adding that list to
the board would strip Andrew's blocked-agent visibility rather than relocate it. That
makes this item's real size larger than the four text edits alone.

**Size.** Small for the four reword-only edits; medium-to-large if it must also add a
NEEDS YOU list to the board itself first (which DESIGN-TRUTH.md's "only `sb board` is
his" arguably requires) — recommend scoping that board addition as its own explicit
sub-item rather than folding it in silently.

---

## A — `sb done` still costs the agent its herdr name

**What happens today.** Live and reproducible, and it is the mirror image of 1.9's fix,
not a leftover instance of the same bug. `report_state` (`switchboard/herdr.py:754-802`,
i.e. `pane report-agent`) is the eviction mechanism — its own docstring now says so in as
many words: "This costs the agent its name, permanently... `Broker.done` is the only
caller left, on an agent that has just said it is finished" (herdr.py:767-783).
`Broker.done()` (`broker.py:3283-3284`) calls `store.set_state(..., "done")` then
`self._push_state(a, IDLE, summary)`, and `_push_state` (`broker.py:4181-4192`)
unconditionally calls `report_state` whenever the agent still has a `pane_id`. `block()`
had the equivalent call removed in `2fce8cc` for exactly this reason; `done()` still has
it, and `herdr.py`'s docstring treats that as intentional, not an oversight.

Concretely: once `done()` runs, `agent get`/`agent prompt <name>` return
`agent_not_found` for that agent's pane, permanently — confirmed via
`_finished_and_unreachable` (`broker.py:3808-3842`) and its use in `_ring`
(`broker.py:3991-4020`), which returns `ring_skipped reason="finished"` for exactly this
case. So no future `sb tell` can ever reach a `done` agent's pane by name again, even
though the pane, its transcript, and its mailbox may still exist and be inspectable.

**Whether it's a bug is a judgement call, not a fact I can settle by reading code** — the
docstring frames the trade as deliberate (a finished agent's turn is over; losing reach is
an acceptable cost). But it directly matches what the brief describes ("the same way
blocking used to evict an agent's herdr name") and the brief's own example — being unable
to send a follow-up to an agent that had just reported — is exactly this mechanism. I'd
call it real and worth Andrew's decision rather than closing it as "working as intended":
`sb cleanup` deliberately keeps a `done` agent's pane and mail reachable via `sb inspect`
when it has live children (`done()`'s own docstring, `broker.py:3264-3270`), which only
makes sense if follow-up contact is sometimes wanted — and losing the name binding
forecloses that specifically for messaging, while leaving inspection intact. That
asymmetry looks unintended even if the individual call is documented as deliberate.

**Pass/fail test.** Have an agent call `sb done`, then `sb tell` it something. Today:
fails with `agent_not_found` (or the sb-level error that wraps it). If fixed to Andrew's
liking: either the message reaches the agent's pane, or `sb tell` fails with a clear,
different error naming the agent as finished-and-unreachable rather than looking like a
typo'd name.

**What a fix would touch (if any).** `broker.py:3284` (`Broker.done`, drop or gate the
`_push_state` call) and `herdr.py:754-802`'s docstring, which currently documents `done`
as the intended sole remaining caller and would need updating either way the decision
goes.

**Size.** Small mechanically, but gated on a decision, not code — flag for Andrew before
sizing it as work.

---

## B — merged into 2.2 above

Confirmed the same underlying gap the brief suspected: "answering a block by typing into
the pane delivers, but never clears the blocked row" is item 2.2, not a second bug next
to it. See **2.2/B** above for the combined writeup, test, and fix surface.

---

## C — mail to long-dead agents never expires

**What happens today.** Filed as `2026-08-09-233230` (found at
`~/.local/state/switchboard/plugins/report-bug/2026-08-09-233230-...md`): mail to an
agent that later fails or finishes sits in NEEDS YOU forever with panes gone and "nothing
will ever move those rows." Live, confirmed, and it's a display-side gap left behind by a
retry-side fix, not the same bug recurring. The retry storm this filed against (21 failed
re-rings in 71 seconds, per `audit/phase1-acceptance-3.md §6.1`) is already fixed:
`flush_pending`/`_ring` (`broker.py:3852-3909`, `3991-4020`) call
`_clear_unreadable_mail` (`broker.py:3911-3958`) for a `_finished_and_unreachable`
recipient, which stops the retries. But `_clear_unreadable_mail` calls
`store.mark_unannounceable` (`store.py:1360-1369`) whenever the row still has a
`pane_id` — the common case — which sets only `delivered_at`, deliberately leaving
`read_at` NULL ("still readable"). `_unread_counts` (`status.py:627-635`) counts
`WHERE read_at IS NULL`, with no check on `delivered_at`, so the message stays "unread"
forever, and `needs_human` (`status.py:286-299`) includes `unread > 0` — so the agent
never leaves NEEDS YOU, it just silently moves from the "never announced" bucket to the
generic "N unread, not picked up" one (`status.py:1162-1164`). No TTL/expiry exists
anywhere on the `messages` table (grepped `store.py`/`broker.py`, none found), and closing
the pane via `sb cleanup` doesn't touch the `messages` table either, so the row survives
cleanup too.

**Pass/fail test.** Send mail to an agent, then let that agent fail or finish and get
cleaned up. Pass = it eventually drops off `sb status --needs-me`/NEEDS YOU on its own (or
is moved to an explicit "undeliverable" bucket that reads as resolved, not as an open
question). Today: fails — it stays indefinitely.

**What a fix would touch.** `broker.py:3911-3958` (`_clear_unreadable_mail`) and/or
`store.py:1360-1369` (`mark_unannounceable`) to decide the resolution (mark fully read,
vs. a new explicit "undeliverable" status distinct from "unread"), and `status.py:627-635`
/`286-299` if the fix is display-side (a separate bucket) rather than store-side (mark
read).

**Size.** Small-medium — narrow code surface, but needs a decision on what "resolved"
should mean here (silently cleared vs. visibly marked undeliverable), same shape of
decision as item A.

---

## D — `sb status`'s undelivered-mail explanation is wrong for a blocked agent

**What happens today.** Confirmed wrong, and wrong for a more specific reason than "still
citing the old bug." The aggregate UNDELIVERED text (`status.py:1170-1172`, `1179-1180`)
and the per-agent `sb inspect` text (`status.py:1389-1390`) both read "the doorbell is
held while an agent is mid-turn... and released when it goes idle" — unconditionally, for
every agent with undelivered mail, never branching on `a.blocked`/`d.blocked` even though
that field is printed a few lines away in the same function. For a blocked agent this is
false on the current, already-fixed code: `_ring` (`broker.py:4016-4020`) and
`flush_pending` (`broker.py:3901-3906`) hold a blocked agent's mail unconditionally until
the human's answer specifically (`answer=(me == HUMAN)`, `broker.py:3135`) — not until it
"goes idle." `AgentStatus.ringable`'s own docstring (`status.py:257-284`) says as much:
"an agent that is BLOCKED is not idle... the only thing that lifts a block is the human's
answer." Since `2fce8cc`, a blocked agent never transitions through herdr-idle at all, so
"goes idle" describes a mechanism that no longer exists for this case, not merely a stale
description of one that does.

Worth noting for planning: BUILD-PLAN.md lists the underlying hold-until-answered
behaviour as future phase-3 work (3.4), but it's already implemented, apparently as a
side effect of the 1.9/2.2 fix rather than as dedicated phase-3 work — what's still
missing from phase 3 is the delivery-mode framework (3.1) 3.4 was written in the context
of, not the holding behaviour itself. Worth flagging to whoever scopes phase 3.

**Pass/fail test.** Block an agent, send it unrelated mail from a third agent, run `sb
status`/`sb inspect` on it. Pass = the undelivered-mail explanation for that agent says
delivery is gated on the human's answer, not on going idle. Today: fails, text is
identical to the non-blocked case.

**What a fix would touch.** `status.py:1166-1180` and `status.py:1385-1391` — add an
`if a.blocked` / `if d.blocked` branch with text matching `ringable`'s actual behaviour.
No `broker.py` changes needed; the underlying logic is already correct, only the
human-facing text is stale.

**Size.** Tiny — text-only, two spots in one file.

---

## Judgement call — does 2.1's "six places" still need doing?

**My read: no, not as originally framed.** `0f69733` already fixed the actual problem
2.1 exists to prevent: a model dumping paragraphs of findings into `why` because it
believed that was what Andrew reads. The `why` argument is now hard-capped at 200 chars
and single-line by `validate.reason`, every shipped prompt says chat-first in the same
words, and two tests pin that shape going forward — so the content that reaches the five
remaining display surfaces is now, structurally, always a short board tag, not a smuggled
message. Suppressing or hiding those five displays would not fix anything further; it
would just make the board/status less informative, and DESIGN-TRUTH.md's own words
("When something needs me, the board shows it, and `sb block`") say a visible reason on
the board row is exactly the intended UI, not a leak. I'd close 2.1 as done except for
one loose end that's really part of 2.6: `cli.py:866`'s confirmation message to the
blocking agent still names `sb status --needs-me`, not `sb board`, as where the human
looks — that's 2.6's fix, not a separate one. Recommend BUILD-PLAN.md be corrected
in place to record 2.1 as resolved by `0f69733`/`2fce8cc`, with only that one line folded
into 2.6.

---

## Grouping and conflict map

Ten items collapse to **nine** (2.2 and B are one). Of those:

**Already resolved, no code work — flag closed:**
- **2.1** (prompt half fixed by `0f69733`; display half is, in my judgement, not a bug —
  see above).

**Solo, no file overlap with anything else in this phase — safe to run in parallel:**
- **2.4** — `defaults/settings.toml` only. Tiny.
- **2.5** — `board.py:331-344` only (unless 2.6 later adds a NEEDS YOU list to the
  board — see below, watch for a future collision, not a current one).
- **D** — `status.py:1166-1180`/`1385-1391` only, and these exact line ranges are not
  touched by any other item below (2.1's five display surfaces and 2.6's NEEDS YOU
  framing sit at different line ranges in the same file — still worth having one owner
  read the whole file's diff before merging, see next group).

**Cluster 1 — `Broker.done()`, `broker.py:3255-3294`. Same function, must be
sequenced, not parallelized:**
- **2.3** (add a top-level notify/flag) and **A** (decide/gate the `_push_state` call)
  both edit this exact function. Assign one owner, or land A's decision first since it
  changes what `done()` does structurally before 2.3 adds to it.

**Cluster 2 — status.py's human-facing rendering, roughly lines 200-336 and
1117-1165/1345-1391. Overlapping region, not overlapping lines yet, but risky to split
blind:**
- **2.6** (`status.py:1125-1131` NEEDS YOU framing, plus `cli.py:833-838,184,866`)
- **C**'s display-side option (`status.py:627-635`, `286-299`) if that's the fix chosen
  over the store-side option
- These don't collide line-for-line with 2.1 (closed) or D (different lines), but all
  three touch `status.py`'s rendering functions in the same general area. Recommend one
  agent owns all `status.py` human-surface text changes in this phase (2.6 + C's
  display option + D) rather than three agents editing the same file blind — cheaper to
  coordinate up front than to merge-conflict after.

**Cluster 3 — `broker.py`'s mail/block machinery, non-overlapping functions but same
subsystem:**
- **2.2/B** (`_unblock_if_needed`, `broker.py:4126-4149`, plus a new verb + `cli.py` +
  prompts)
- **C**'s store-side option (`_clear_unreadable_mail`, `broker.py:3911-3958`,
  `store.py:1360-1369`) if chosen over the display-side option
- Different functions, no line overlap, but both editing `broker.py`'s undelivered-mail
  logic in the same phase — fine to parallelize, but land C's decision (store vs.
  display) before assigning it, since it determines whether C lands in this cluster or
  cluster 2.

**Coupling to flag, not yet a conflict:** the 2.4-2.6 investigation found `board.py` has
no NEEDS YOU equivalent at all today. If 2.6 is scoped to include adding one (recommended
above, since rewording `sb status`/`sb inbox` to point at `sb board` without it would
strip Andrew's blocked-agent visibility), that lands in `board.py` and would then need
sequencing behind or alongside **2.5**, which is also `board.py`. Recommend scoping that
board addition as its own explicit sub-item under 2.6 so it can be sequenced rather than
discovered mid-flight.

**Decisions needed before sizing, not before starting the read:**
- **A** — is losing the herdr name binding on `done()` actually wrong, or an accepted
  trade for a finished agent? I lean "wrong as an asymmetry" (see above) but it's
  Andrew's call.
- **C** — should undeliverable mail to a dead agent be silently marked read, or surfaced
  as an explicit "undeliverable" state distinct from "unread, not picked up"? Determines
  which cluster (2 or 3) it lands in.

**Recommended run order:** 2.4, 2.5, D in parallel immediately (no dependencies, no
overlap). Get Andrew's calls on A and C's resolution shape first, since both gate which
cluster their work lands in and A gates cluster 1's order. Then run cluster 1 (2.3+A) as
one sequenced unit, cluster 2 (2.6+C-if-display+D-already-done) as one owner, cluster 3
(2.2/B+C-if-store) in parallel with cluster 2 once C's shape is decided.

---

## What surprised me

- Two commits already on this branch (`0f69733`, `2fce8cc`) closed most of what
  BUILD-PLAN.md's 2.1 and phase-1's 1.9 describe, and did it as a byproduct of fixing the
  herdr name-binding loss for `block()` — which is the exact mechanism still live for
  `done()` in finding A. The plan and the phase-1 audits it's built from are meaningfully
  stale on this corner already.
- Phase 3's item 3.4 ("hold when-idle mail until a block is answered") is already true in
  the current code, apparently for free, as a side effect of the block fix rather than
  planned phase-3 work — worth flagging to whoever scopes phase 3 next.
