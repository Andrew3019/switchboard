# Phase 3 scope — messaging

Read-only audit. Base: this branch's tip, `b2a3e47` (`main`, phases 1 and 2 merged), plus
nothing but this file. Modelled on `audit/phase2-scope.md`. Covers BUILD-PLAN.md's
3.1–3.6 plus one thing neither BUILD-PLAN.md nor DESIGN-TRUTH.md names: the collector can
run stale, pre-fix code for as long as a board pane stays open, and that is a live,
unfiled bug, not a hypothetical (see **3.7**).

Ground truth taken as given, not re-derived: `DESIGN-TRUTH.md:92-106` (how herdr actually
talks to Claude; the three delivery modes) and `:230-258` (the `tell`/`ask`/`block` product
decisions, including "no agent ever waits on another agent" and "`sb ask` should not
exist"); `audit/delivery-modes.md` on branch `delivery-experiment` (live measurement of
`interrupt` vs. busy-`tell` vs. idle-`tell` against an isolated clone at this same commit).

**Headline finding, stated up front because it changes how much of this phase is real
work.** `audit/phase2-scope.md` — written on an earlier commit of this same branch —
found 2.2/B, 2.3, and A still open, and found D's stale "goes idle" text present. All four
are now fixed on `main` as read today, apparently as further fallout of the block/name-
binding fix that closed most of 2.1 and phase-1's 1.9: `Broker.done()`
(`broker.py:3358-3423`) now calls `self._surface` for a root's `done`
(`broker.py:3422`, pinned by `tests/test_broker.py::test_a_root_agents_done_is_announced_because_nothing_else_will`
at line 618) and never calls `report_state`/`_push_state` at all — grep for
`report_state\|_push_state` in `broker.py` finds it only in comments and a docstring
(`broker.py:4343-4346`) explaining why there is no such call any more. And `Broker.whoami()`
→ `_revive()` (`broker.py:505-585`) now clears a block the moment the agent runs its next
`sb` command from inside its own pane — `_revive`'s docstring (`broker.py:545-570`) states
this in as many words, and it is pinned by
`test_answering_in_the_pane_clears_the_block_and_releases_its_mail`
(`tests/test_broker.py:693-717`). `status.py:1201-1218` and `:1425-1438` also now branch on
`a.blocked`/`d.blocked` for the UNDELIVERED text, so item D is fixed too. **None of this is
phase-3 work; it is already done, and this document does not re-list it.**

---

## 3.1 — `sb tell` gains three delivery modes

**What happens today.** One mode exists, unconditionally: `Broker.tell()`
(`broker.py:3196-3239`) always calls `self._ring(t, ...)` with no `force`, and `_ring`
(`broker.py:4146-4222`) defers — `ring_deferred`, `broker.py:4207-4209` — whenever
`self._busy(who)` (`broker.py:3989-3995`, herdr state `WORKING`) is true, resuming only
once the agent goes idle. That is *when idle*. There is no CLI surface for a mode at all:
`sb tell`'s parser (`cli.py:155-158`) takes only `who`, `message`, and a hidden `--re`;
nothing chooses *next turn* or *interrupt*. *Interrupt* is the separate `sb interrupt`
verb (`cli.py:305`, dispatched at `cli.py:1000-1003`) → `Broker.interrupt()`
(`broker.py:3840-3882`), which sends `esc` first (`stop=True` default, no CLI flag reaches
`stop=False`) and always wraps the text in the `notify.interrupt` cancel-your-work template
(`defaults/prompts.toml:82-90`), then rings with `force=True`.

**This corrects BUILD-PLAN.md's own framing**, and `audit/delivery-modes.md` already said
so once: *next turn* is not "the herdr path `sb interrupt` already uses, lifted out" —
`interrupt` bundles a forced ring with an escape keypress and a cancellation wrapper, and
there is no non-cancelling variant of that path today.

**What I can add past the delivery-modes audit, from the code the audit did not run
against directly.** The audit measured the *deferred* busy-`tell` path (5m37s wait,
delivered only once the agent's turn ended on its own) — it never called the raw ring
primitive on a busy agent, because `_ring`'s busy-check stopped it from trying. That
primitive is `Herdr.prompt()` (`herdr.py:480-494`), and its own docstring says, re-verified
against a genuine 60-second multi-step turn: **"This INTERLEAVES. It does not queue."** —
a poke was *handled* at +13s while the task it interrupted did not complete until +63s.
`_ring`'s own comment (`broker.py:4150-4153`) agrees: "`agent prompt` INTERLEAVES,
injecting into the current turn rather than queueing after it." Both are internally
consistent with each other. Neither is consistent with
`DESIGN-TRUTH.md:96-97`: "While Claude is working, a message is queued by Claude's own
system and delivered on the next turn" — which is the entire premise BUILD-PLAN.md's 3.1
and the phase-2 audit's "worth flagging to whoever scopes phase 3" note both rest *next
turn* on.

**I did not resolve this myself — read-only scope, and it is exactly the kind of
contradiction-with-DESIGN-TRUTH the house rules say to stop and flag rather than silently
side with the code.** But it is the fact that determines 3.1's size: if `agent prompt`
really interleaves rather than queues, then dropping the busy-gate to build *next turn*
does not produce "paste now, land at the next step boundary" — it produces "paste now,
land inside whatever tool call is running," i.e. an interrupt without the cancellation,
which is a materially different and riskier primitive than either mode DESIGN-TRUTH
describes. It is possible the human-typed path (character-by-character into the literal
terminal, not `agent prompt`'s API call) behaves differently and is what DESIGN-TRUTH is
actually describing — herdr.py's docstring does not distinguish the two. That distinction
is the one live test I'd recommend before sizing further, and it is a few minutes of work
in an isolated clone: send text via `agent prompt` to a busy agent mid-tool-call (not
between steps, unlike the one `interrupt` sample the delivery-modes audit caught) and read
whether it interleaves or waits.

**Pass/fail test.** `sb tell <busy-agent> "..."` with no flag delivers at the agent's next
step boundary, without cancelling the step in progress — pass if the in-flight tool call
completes and *then* the message appears; fail if the message appears via a cancelled turn
(today's only path) or not until full idle (today's default and only behaviour).

**What a fix would touch.** `broker.py` (`tell`, `_ring`, possibly a new `Herdr` call if
the live test above shows `agent prompt` cannot produce non-cancelling delivery),
`cli.py:155-158` (a mode flag or three call shapes), `defaults/prompts.toml`'s `[notify]`
block, and role/protocol text describing the modes — none of which exists today
(`defaults/protocol.md`, role prompts describe only `tell` and `block`, no modes).

**Size.** Large, and gated on the decision/live-test above before it can be sized tighter
— possibly small if the human-typed path turns out to differ from `agent prompt` and a
thin wrapper is all that's needed; possibly requiring new herdr capability if it does not.

---

## 3.2 — delete the `sb interrupt` verb once it is a mode

**What happens today.** `sb interrupt` is a live, separate CLI command
(`cli.py:305` parser, `cli.py:1000-1003` dispatch) and a separate `Broker` method
(`broker.py:3840-3882`), fully independent of `tell`. BUILD-PLAN.md's own ordering rule
applies literally: delete it before 3.1 lands a mode that carries the same capability, and
the capability is gone with no replacement.

**Pass/fail test.** After 3.1 ships an `interrupt` mode on `tell`: `sb interrupt` must no
longer parse (fail = it still runs); the interrupt capability itself must still work via
whatever `tell` spells it as (fail = capability lost, not just the verb).

**What a fix would touch.** `cli.py:305` (parser removal) and its dispatch block
(`cli.py:1000-1003`); `broker.py:3840-3882` (`interrupt`) either deleted or kept as the
private implementation `tell`'s interrupt-mode branch calls into; role/protocol prose that
currently doesn't mention `sb interrupt` by name anyway (grep of `defaults/` finds no
shipped prompt teaching it, so this is a code-only deletion, not a prompt rewrite).

**Size.** Tiny, mechanical — but strictly *after* 3.1, never before, per BUILD-PLAN.md's
own rule, which the code still supports today (nothing pre-empts it).

---

## 3.3 — every `sb` message carries `[sb: from <name>]`

**What happens today.** Nothing is marked. `defaults/prompts.toml`'s `[notify]` block
(`:61-90`) is the entire text vocabulary a doorbell or an interrupt ever puts in front of
an agent — `mail = "You have mail. Run: sb inbox"` (`:65`), `mail_question` (`:71`),
`child_done` (`:82`), `interrupt` (`:90`) — and none names the sender or marks itself as
sb-authored text as opposed to Andrew's own typing (the exact ambiguity
`DESIGN-TRUTH.md:93-95` and `:101-103` exist to remove: "a message from sb arrives looking
exactly like one Andrew typed... they are the same thing to Claude"). The one place a
sender name appears at all is `sb inbox`'s own output formatting, `cli.py:853`:
`f"[{m['id']}] from {m['from_agent']}: {m['body']}"` — visible only *after* an agent runs
`sb inbox` in response to the doorbell, and in a different shape (`[id] from X: body`,
not `[sb: from X]`). The doorbell text itself, and the interrupt body that goes straight
into the pane inline (`broker.py:3876`, `body = self._say("notify.interrupt", text=text)`),
carry no such marker at all.

**Pass/fail test.** Any text an `sb` command puts in an agent's pane — doorbell, inline
interrupt body, or a message body surfaced via `sb inbox` — contains a recognizable
`[sb: from <name>]`-shaped tag. Fail = today's state: doorbell text names no sender,
interrupt text names no sender, and `sb inbox`'s tag is spelled differently and only
reachable a step later.

**What a fix would touch.** `defaults/prompts.toml:61-90` (all four `[notify]` strings,
adding a `{from}`-shaped field), `broker.py:3238,3283,3413,3876,4052` (every `_say(...)`
call site, to pass the sender), and `cli.py:853` (`sb inbox`'s own formatting, to match the
same tag rather than a different one).

**Size.** Medium — narrow files, but touches every message-construction site in
`broker.py` and needs one consistent tag shape decided once, not per site.

---

## 3.4 — hold when-idle mail until a block is answered

**Already true — confirmed fixed, and confirmed for a second time past
`audit/phase2-scope.md`'s finding.** `_ring` (`broker.py:4202-4209`) and `flush_pending`
(`broker.py:4046-4051`) both hold a blocked agent's mail unless the message is the human's
own answer (`answer=(me == HUMAN)`, `broker.py:3238`); `status.py:1201-1218` and
`:1425-1438` describe this correctly to a human reader, branching on `a.blocked`/`d.blocked`
rather than repeating the old, wrong "goes idle" text unconditionally. `audit/delivery-
modes.md` observed the same thing live: `expt-top` blocked while six children's `done`
reports queued behind it and stayed queued for the eleven minutes the experiment ran.
Nothing in this item needs code. Recorded here, as `audit/phase2-scope.md`'s "D" already
flagged, only so whoever runs phase 3 does not re-do it.

**Size.** Zero — flag closed.

---

## 3.5 — the reconciler

**What happens today.** Detection exists and is exact, nothing acts on it.
`AgentStatus.stalled` (`status.py:211`, computed at `:508`) is `True` exactly when an agent
is `running`, herdr reports it `alive` and in an idle-like herdr state, and it is not
`awaiting_task` (spawned with a placeholder, never yet given real work,
`store.py:166`/`broker.py:2931`) — i.e. its turn ended without a `done` or a `block`.
`collector.py:172-174` names this explicitly as unbuilt: "An agent that is idle without
having reported is a different problem with a different answer (the reconciler, phase
3.5), and a half of it built here would be thrown away." Grepping the whole tree for
`reconcil` finds only that comment and unrelated store-schema reconciliation
(`store._reconcile`) — nothing pings a stalled agent anywhere.

**One piece 3.5 is described as covering does not exist yet at all.** BUILD-PLAN.md says
the reconciler "also covers an unanswered `--needs-reply`", and `DESIGN-TRUTH.md:232-234`
describes `tell --needs-reply` as inserting a static prompt that the target must reply at
some point. Grepping `cli.py`, `broker.py`, `defaults/*.toml`, `defaults/roles/*.md` for
`needs-reply`/`needs_reply` finds nothing — the flag, the store state it would need, and
the prompt text are all unbuilt. 3.5 as scoped by BUILD-PLAN therefore has a prerequisite
that is not itself phase-3-numbered anywhere.

**Pass/fail test.** Let an agent's turn end without `sb done` or `sb block`. Pass = within
one reconciler cycle it receives a ping telling it to report one or the other. Today:
fails — `sb status`/the board correctly show it `stalled` (`status.py:1180-1188`), but
nothing is sent to it; it sits until a human or another agent's unrelated message happens
to ring it.

**What a fix would touch.** A new loop or an addition to an existing one —
`collector.py`'s own comment suggests "maybe the same loop `sb board` runs on"
(`DESIGN-TRUTH.md:129`), which would mean `collector.tick()` (`collector.py:283-309`)
gaining a second trigger alongside `ring_doorbell`, rate-limited the same way
(`DOORBELL_GAP`-shaped, so a stalled agent that stays stalled for an hour does not spawn an
`sb` every two seconds); a new `notify.*` template; and, if `--needs-reply` is scoped in
here rather than built first, `store.py` (a column), `validate.py`, `cli.py`'s `tell`
parser, and role/protocol prompt text.

**Size.** Medium-large — the core ping is a small, well-bounded addition once a trigger
point is chosen, but `--needs-reply` is unbuilt from zero and inflates this item
considerably if it stays folded in; recommend scoping `--needs-reply` as its own small
sub-item, built first, the same way `audit/phase2-scope.md` recommended splitting the
board's NEEDS YOU list out of 2.6.

---

## 3.6 — remove `sb ask`

**What happens today.** Fully live. `cli.py:146-153` parses it; `cli.py:387-390` validates
it; `cli.py:776-782` dispatches it; `Broker.ask()` (`broker.py:3241-3320`) blocks the
calling process in a poll loop (`ASK_TIMEOUT`/`ASK_POLL`) until every target answers or
vanishes. `store.pending_ask` (`store.py:1434-1449`) is the mechanism `tell` checks to
auto-reply an open ask (`broker.py:3216-3218`) — so the store structurally still holds
"live ask rows" any time an `ask` is outstanding and unanswered, exactly as BUILD-PLAN.md
says. It is still taught: `defaults/protocol.md:124` tells every agent `sb ask <who>
"<question>" sends to another agent and WAITS for its answer — for agents only" (this very
session's own system prompt carries that line verbatim, which is itself a small live
demonstration that the removal has not happened).

**Pass/fail test.** `sb ask` does not exist as a command (fail = it still parses); no
shipped prompt still describes it (fail = grep of `defaults/` still finds it, as it does
today at `protocol.md:124`).

**What a fix would touch.** `cli.py:146-153,387-390,776-782` (parser, validation,
dispatch), `broker.py:3241-3320` (`ask` itself, plus the `reply_to` auto-answer path in
`tell` at `:3216-3234`, which would need to either go with it or be repointed at whatever
3.1 lands for "wait for an answer" — DESIGN-TRUTH says no agent should ever wait on another,
so the likely resolution is deletion, not a repoint), `defaults/protocol.md:124` and any
role prompt mentioning it.

**Size.** Small — mechanical once 3.1 exists to replace the one legitimate half of `ask`'s
job (getting a message to a busy target reliably); strictly *after* 3.1, per BUILD-PLAN.md's
own rule, which is also why this can't be sized as "tiny" — it is gated on 3.1's shape, not
just its landing.

---

## 3.7 — the collector can run stale, pre-fix code for as long as any panel stays open

**Not in BUILD-PLAN.md.** New, and not a hypothetical: the brief for this document names a
same-day incident — a top orchestrator's mail sat undelivered for close to four hours, and
the cause was traced to a day-old collector process still running pre-fix code as its
doorbell. This item explains the mechanism and confirms it is real and unpatched.

**What happens today.** Exactly one collector runs per repo, elected by an `flock` it holds
for its entire life (`panel.py:41-52`, `collector.py:312-325`). Once elected it never
re-checks its own code: `collector.py`'s own module docstring states this as the design,
not an oversight — "`readonly=True` and `reap=False` are load-bearing... this process
outlives the code it started with. It ticks for hours against the `status.py` and the
`store.SCHEMA` string that existed when the human opened a panel, so anything it writes is
written by a version nobody is running any more" (`collector.py:13-22`). It is not killed
and re-elected when the checkout it was started from changes — nothing watches for that.
The only thing that ends it is every panel going quiet for `panel.collector_idle_exit`
(60s, `defaults/settings.toml:431`) — `collector.py:359-371`,
`_nobody_is_looking` — and the only thing that starts a new one is a renderer finding the
lock free. If a board (or any panel) is left open, the collector behind it is never
replaced, however old its in-memory code gets.

This matters specifically for the doorbell, because the doorbell is the one thing this
process does on its own initiative: `ring_doorbell` (`collector.py:162-211`) runs
`sb flush` in a thread every tick, gated only by `DOORBELL_GAP` (10s,
`collector.py:92`) and whether anything is `ringable`. `doorbell_sb()`
(`collector.py:214-240`) already defends against one staleness failure — a collector
spawning the *wrong build's* `sb` off `PATH` (`collector.py:217-231`, the 55-failed-
doorbells incident it cites) — by always running *this checkout's* `bin/sb`. But that
checkout is fixed at the collector's own start time; if the collector process itself has
been running since before a delivery-path fix landed (any of the fixes phase 1/2 made to
`_ring`, `_busy`, `_finished_and_unreachable`, `block`/`done`'s name-binding calls, etc.),
it keeps executing that pre-fix Python in memory tick after tick, spawning a *correct*
`sb flush` each time but deciding *whether* and *whom* to ring with logic that predates
the fix. No version, commit hash, or code signature is published anywhere: grepping
`collector.py`/`panel.py` for `version`/`commit`/`sha` finds only prose, no mechanism —
`sb doctor`'s `panel pid ...` line names a process, not a code version.

**Pass/fail test.** Start a collector from checkout A (containing a since-fixed doorbell
bug); leave one panel open so it never exits; land the fix on checkout A's own files (a
`git pull` or equivalent, not a new checkout); trigger the condition the fix addresses.
Pass = the *next* tick behaves per the new code (requires either a restart or some
mechanism that makes the running process re-read it — neither exists). Fail = today's
behaviour: the old in-memory code keeps running, unchanged, until every panel closes for
60 seconds.

**What a fix would touch.** No existing surface does this; it needs a new mechanism, and
there's a decision to make about its shape before sizing:
- **Cheapest:** stamp the collector's `State` with something that identifies the code it
  loaded (a commit hash via `git rev-parse HEAD` at startup, or an mtime/hash of the
  relevant `.py` files) and have `panel.ensure_collector`/a renderer compare that against
  the checkout it itself sees on every draw; if they differ, kill the collector (it holds
  the `flock` via an fd — closing that from outside means signalling the pid, which
  `collector.py`'s `_stop_on_signal` (`:374-387`) already handles cleanly) and let the next
  renderer's tick re-elect a fresh one. Touches `collector.py` (`State`, `run`) and
  `panel.py` (`ensure_collector`, wherever it is called from).
  - Deliberately does not try to distinguish "the code changed" from "a different worktree
    of the same repo changed" — `git_common_dir` is one per repo, shared across worktrees,
    so a collector elected from worktree A is genuinely running worktree A's code while
    worktree B's changes sit unnoticed; a version stamp keyed on the electing checkout's
    path, not just its commit, would be needed if that distinction matters to Andrew.
- **More invasive:** shorten `collector_idle_exit` so staleness self-heals faster — treats
  the symptom, not the cause, and does nothing for the reported incident (a board stayed
  open for hours, so nothing this settings value could plausibly be set to would have
  helped without also making an active session's collector restart constantly).

**Size.** Small-medium for the "cheapest" option above — two files, no new subsystem — but
gated on Andrew's call about what "the code changed" should mean (commit hash vs. file
signature vs. per-worktree-path) before it can be sized tighter; flag for a decision the
same way items A and C were in phase 2.

---

## Grouping and conflict map

**Already resolved, no code work — flag closed:**
- **3.4** — confirmed fixed on `main` as read today (see headline finding and its own
  section above).

**Solo, no file overlap with anything else in this phase — safe to run in parallel,
immediately:**
- **3.7** — `collector.py`/`panel.py` only, a different subsystem from the `broker.py`/
  `cli.py` messaging work everything else here touches. No dependency on 3.1's outcome.

**Decision needed before sizing, not before starting the read:**
- **3.1** — does `agent prompt` (the only ring primitive) interleave or queue when sent to
  a busy agent without `esc`? The code's own re-verified docstrings say interleave;
  DESIGN-TRUTH's product decision says queue. One live test in an isolated clone (send via
  `agent prompt` to an agent mid-tool-call, not between steps) resolves it and this gates
  everything below it.
- **3.7** — what should "the collector's code changed" mean: commit hash, file signature,
  or something scoped per-worktree? Gates exactly how the restart-on-change check is
  written, not whether it's needed.

**Strictly sequenced, per BUILD-PLAN.md's own rule — same reason each time (delete the old
thing only once its replacement exists), and all three touch the same `broker.py`
tell/interrupt/ask cluster (`broker.py:3196-3320`, `3840-3882`) plus `cli.py`'s parser
block (`:130-160`, `:305`), so one owner for the whole chain is cheaper than three handoffs:**
- **3.1** (build the modes) → **3.2** (delete `sb interrupt`) → **3.6** (delete `sb ask`,
  and repoint or delete `tell`'s `reply_to` auto-answer path that depends on it).

**Couples tightly with 3.1, not strictly after it:** 
- **3.3** — every site it touches (`broker.py:3238,3283,3413,3876,4052`, all `_say(...)`
  calls) is a site 3.1 is also going to edit, since 3.1 changes what `_ring`/`tell` do at
  exactly those call sites. Same recommendation `audit/phase2-scope.md` gave for its own
  `status.py` cluster: one owner for both, or land 3.1's shape first and add the sender tag
  as part of the same pass rather than a second pass over the same lines.

**Own track, lightly coupled to 3.7 through one shared file:**
- **3.5** — the core reconciler ping does not need 3.1 (its targets are idle by
  definition, and today's idle-`tell` already lands the same second per the delivery-modes
  audit), so it can proceed independently of the 3.1 decision above. It likely lands in
  `collector.py`'s tick loop, the same file 3.7 changes the lifecycle of — recommend 3.7
  land first (it changes when a collector process ends, which 3.5's new per-tick trigger
  would otherwise be added on top of and then have to revisit) or assign one owner to both.
  The `--needs-reply` flag BUILD-PLAN.md folds into 3.5 does not exist in any form yet
  (confirmed by grep — no code, no store column, no prompt text) and is real, separate,
  ground-up work; recommend splitting it out as its own small first step rather than
  discovering its size mid-flight, the same way the phase-2 audit recommended splitting a
  NEEDS YOU board addition out of 2.6.

**Recommended run order:** 3.7 immediately, in parallel with getting Andrew's decision on
3.1's live-test question and 3.7's own "what counts as changed code" question. Build
`--needs-reply` as a tiny standalone step whenever convenient (no dependency on anything
else in this phase). Once 3.1's shape is decided: one owner runs 3.1+3.3 together, then
3.2, then 3.6, in that order. 3.5's reconciler proper starts once 3.7 has landed (shared
file) and `--needs-reply` exists, and does not need to wait on 3.1.

---

## What surprised me

- **Three of `audit/phase2-scope.md`'s open findings (2.2/B, 2.3, A) and one of its "text
  is stale" findings (D) are fixed on `main` as read today**, on a commit of this same
  branch written after that document. All four are pinned by tests
  (`tests/test_broker.py::test_a_root_agents_done_is_announced_because_nothing_else_will`,
  `::test_answering_in_the_pane_clears_the_block_and_releases_its_mail`, and the
  blocked-branching text at `status.py:1201-1218`/`:1425-1438`). Nobody scoped these as
  phase-3 work and nobody needs to now — but it means `audit/phase2-scope.md` itself is
  stale on exactly the items it flagged as needing a decision from Andrew (A's judgement
  call, in particular, appears to have been resolved in the same direction I'd have
  recommended, without it being logged as a decision anywhere I can find).
- **`DESIGN-TRUTH.md`'s account of how "next turn" delivery is supposed to work conflicts
  with the code's own, twice-re-verified account of the only primitive that could deliver
  it.** I did not resolve this — see 3.1 — but it is worth Andrew's attention on its own,
  separate from sizing: either `herdr.py`'s docstring is wrong about a mechanism it says it
  re-verified, or the product decision at `DESIGN-TRUTH.md:96-97` was written from how a
  *human* typing into the chat box behaves and never checked against what `agent prompt`
  (the API path `sb` actually uses) does to a busy agent.
- **`--needs-reply` does not exist anywhere in the code**, despite being named in both
  `DESIGN-TRUTH.md:232-234` and BUILD-PLAN.md's 3.5 as something 3.5 "also covers." It is
  not a partially-built feature; grep finds zero hits across `cli.py`, `broker.py`,
  `store.py`, `validate.py`, and every shipped prompt.
- **The collector-staleness bug (3.7) has no filed report** in
  `~/.local/state/switchboard/plugins/report-bug/` as of this read (most recent entry
  2026-08-09; today is 2026-08-11) — it is a live, reproducible design gap, not yet in the
  bug store phase 1/2 were scoped from.
