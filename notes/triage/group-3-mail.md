# Group 3 — mail delivery and the doorbell

Triaged against HEAD (`fb04859`) of the `bug-triage` worktree, 2026-08-15. All five reports
were filed 2026-08-08/09; every mechanism below landed after the last of them.

## 2026-08-09-233230-mail-written-to-an-agent-that-later

**Verdict:** FIXED
**Severity:** high (was: permanent noise in the human's only queue)
**Evidence:** by reading. `0b9b582` "Stop ringing agents that have finished, and unjam the
rows it left" added `Broker._clear_unreadable_mail` (broker.py:4242), which names this
report id in its own docstring. Mail to an agent that finished with its pane gone is
stamped `undeliverable_at` (`store.mark_undeliverable`, store.py:1619, also citing the id);
`status._unread_counts` (status.py:1201-1203) excludes those rows, which is what takes the
agent out of NEEDS YOU. Mail for a finished agent whose pane is still open gets the softer
`mark_unannounceable` (store.py:1599) — `delivered_at` stamped, `read_at` untouched — so it
leaves `unseen()` and stops the retry loop while its `sb inbox` still hands it over. Nothing
is destroyed: `sb inspect` and `sb restore` still reach it. Covered by
`tests/test_broker.py:1133` and `:1147`; both pass at HEAD.
**Same-as:** 2026-08-08-145402 (the same "mail owed to a finished agent" family, the other
half of it).

## 2026-08-09-004538-mail-to-an-idle-agent-is-never

**Verdict:** FIXED
**Severity:** high (was: instructions silently lost for 40m+)
**Evidence:** by reading. Both halves of the report are closed by two commits.
(a) *Never announced:* `051e4af` "1.3: the collector rings the doorbell on a timer" — the
collector spawns `sb flush` every 10 s while any agent is `ringable`
(collector.py:204-254), on top of `flush_pending` running at the start of every `sb`
command (broker.py:4155). An idle agent with pending mail is now rung within one tick
without anyone touching the store.
(b) *The gate and the readout disagreeing:* since `4fc4328` ("activity signal") both read
the same column. `Broker._busy` (broker.py:4148) reads `agents.turn` first and falls back
to herdr only when it is NULL; `status.collect`'s `turn_over` (status.py:849) does exactly
the same. With `turn` set they cannot differ; with `turn` NULL, `_busy` is
`herdr == working` and `turn_over` is `herdr in idle_like`, which are disjoint — so the
"tell says mid-turn / status says idle" contradiction has no path left. Not proven by a
live run: reproducing it needs herdr's busy detector to misread a pane, which I cannot
stage. The residual risk is exactly report 2026-08-09-045325 below.
**Same-as:** 2026-08-09-045325 (very likely the same stale `working` edge, seen from the
sender's side), 2026-08-09-035933.

## 2026-08-09-035933-a-parent-in-a-long-interactive-turn-is

**Verdict:** FIXED
**Severity:** medium (was: an orchestrator misses its whole cohort)
**Evidence:** by reading. `done`'s poke to the parent is still WHEN_IDLE on purpose
(broker.py:3525-3531, DESIGN-TRUTH.md:366-370) — holding it while the parent is mid-turn is
intended. What was missing was anything to release it, and `051e4af` supplies it: the
collector re-rings via `sb flush` every 10 s for as long as the parent has undelivered mail
(collector.py:204), and `flush_pending` fires on any `sb` command from anywhere in the
fleet. A parent talking to a human ends a turn between prompts, and the ring lands at the
first tick after that. Regression test:
`tests/test_broker.py:856 test_a_parent_that_was_mid_turn_is_woken_by_the_next_flush`,
passing at HEAD.
**Same-as:** 2026-08-09-004538 (same doorbell-never-released complaint, different trigger).

## 2026-08-08-145402-mail-to-a-child-that-already-called-sb

**Verdict:** FIXED
**Severity:** medium
**Evidence:** by reading. The root cause was ours: `sb done` used to call `pane
report-agent`, which evicts herdr's name binding for good (`Herdr.report_state`,
herdr.py:886-912) — hence `agent_not_found` against a live pane. `14fa06c` "Finishing no
longer costs an agent its name" removed that call; `Broker.done` now reports nothing to
herdr and says so in place (broker.py:3514-3516). A finished agent with a live pane
therefore still binds, so `_finished_and_unreachable` (broker.py:4126) is false, `_ring`
announces the mail normally, and the parent can hand follow-up work to a finished child.
The UNDELIVERED-forever half is closed by `mark_unannounceable`
(see 2026-08-09-233230). Where the pane really is gone, `_interrupt` now refuses in plain
words — "has already finished — there is no turn to interrupt", broker.py:4000-4009 —
instead of raising a herdr failure.
Caveat, reported not fixed: `Broker._name_bound`'s docstring (broker.py:4062) still says
"`sb done` evicts the name binding", which `14fa06c` made false. Stale prose in a comment,
no behaviour attached. Same for `_binding_lost` (broker.py:4415), which still lists
`Broker.done` as a live caller of `report_state`.
**Same-as:** 2026-08-09-233230.

## 2026-08-09-045325-an-interrupted-turn-leaves-an-agent

**Verdict:** PARTLY FIXED
**Severity:** medium
**Evidence:** by reading. *Fixed half:* the wedge is no longer permanent. `536caa1` added
`AgentStatus.turn_doubted` (status.py:477) and `status._forget_turn` (status.py:1017): a
`working` edge with no event of its own for `turn_stale_grace` (1800 s) while herdr reports
the pane idle is doubted, and if the doubt holds for `turn_doubt_grace` (900 s) the column
is set back to NULL — at which point `_busy` reads herdr again and the held mail is rung.
`4dc58b2` closed the hole that stopped this ever firing: `ring_deferred` and friends are in
`status.DONE_TO_THE_AGENT` (status.py:312), so a `tell` held for a wedged agent no longer
resets that agent's own idle clock.
*Not fixed:* the cause is untouched. An interrupted turn still fires no `Stop` hook, so
`agents.turn` stays `working` and the report's exact symptom — `sb tell` answering
"mid-turn — will be rung when free" while the pane sits at an empty prompt — still holds
for up to 45 minutes. Nothing in `hooks.py` or `status.py` names the interrupt case at all
(`signal_drift` and `turn_doubted` name crashes, `/exit`, and lost hook writes). Not
live-run: proving the 45-minute repair needs a 45-minute wait, which the "smallest run"
rule rules out; the 45 minutes is read off `defaults/settings.toml:279,290`.
**Issue title:** An interrupted turn is never closed, so an agent's mail is held for up to
45 minutes while its pane sits idle
**Issue body:**
Pressing escape in an agent's pane cancels the turn without firing Claude Code's `Stop`
hook, so `switchboard/hooks.py` never writes the turn-ended edge and `agents.turn` stays
`working`. `Broker._busy` (broker.py:4148) trusts that column ahead of herdr, so every
`--when-idle` doorbell to that agent is deferred, `sb tell` answers "mid-turn — will be
rung when free", and the agent sits at an idle prompt with unread instructions it has no
way to learn about. `sb status` shows `working` / UNDELIVERED n against a pane that is
plainly at its prompt.
It self-repairs, but slowly: `status.turn_doubted` needs 30 minutes of quiet
(`timeouts.turn_stale_grace`) plus 15 minutes of sustained doubt
(`timeouts.turn_doubt_grace`) before `status._forget_turn` drops the edge. That is the
difference between the wedge being permanent and being a 45-minute stall — it is not the
same as the turn ending. Any signal that an interrupt happened (a `SessionEnd`/`Notification`
edge, or letting a herdr `idle` reading close an edge whose agent has run an `sb` command
since) would close it at the pane instead. Worth deciding whether 45 minutes is acceptable
for a hand-driven interrupt, which is a common thing to do to an agent.
**Same-as:** 2026-08-09-004538 (its "idle but reported mid-turn" is most likely this).

---

Not encountered in this group: anything matching #38, #40 or #41.
