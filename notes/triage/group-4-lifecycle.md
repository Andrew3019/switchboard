# Group 4 — agent lifecycle, state, and cleanup

Triaged against HEAD `fb04859` of this worktree. Live runs were made in a throwaway
`git clone` under my scratchpad (its own store under the clone's `.git`), driving that
clone's own `./bin/sb`; the clone is deleted. Read-only queries against the live store
(`/Users/andrew/Code/switchboard/.git/agentflow/state.db`) were used to read the history
of the two agents named in the newest report — that history is the strongest evidence in
this group.

Three still broken (one high), three fixed.

---

## 2026-08-14-125645-two-children-sit-at-state-working

**Verdict:** STILL BROKEN
**Severity:** high
**Evidence:** by reading + by the live store's own record of the reported incident. Nothing
under `switchboard/` touching lifecycle or mail has landed since the report's `4ba6c99`
(`git log 4ba6c99..HEAD -- switchboard/` is board/roles/docs only). The event log for the
two agents named in the report:

- `worker-24`: `turn_start` 12:25, `interrupt` 12:36, then **no event of its own ever
  again**. `cleanup_refused "working, not finished — it has not reported an end"` at 12:57
  and again at 14:04. `turn_forgotten {"held": 2700}` at 14:01 — the 45-min turn-doubt
  repair (`status.turn_doubted` + `_forget_turn`, status.py:477/1017) did fire. The row
  still sat at `working` until a human `cleanup --force` at **19:05**, 6.5 hours later,
  which cleared two messages `mail_cleared` — still unread.
- `researcher-20`: same shape (`interrupt` 12:40, silent after), two identical
  `cleanup_refused`, `turn_forgotten` at 14:01, and only recorded `gone`/`failed` at 19:03
  when herdr finally dropped its pane.

So the doorbell half is mitigated (the stale `working` edge is dropped after
`turn_stale_grace` + `turn_doubt_grace` = 45 min), but the reported condition is real and
is what a parent hits: for the first 45 min the row is indistinguishable from a live
working agent, and `agents.state` never leaves `working` at all. There is no path from
`working` to any finished state for an agent whose session died mid-turn while herdr still
lists its pane — `status.needs_human`'s own docstring (status.py:578-588) says exactly
this: "the store will say `working` about it forever, no doorbell will ever ring it again,
and `sb cleanup` will not touch a row that is not finished. Nothing in the fleet moves it."
`--force` is the only exit and nothing tells the caller that.

Not a general `--interrupt` fault: of 13 `interrupt` events in the store, 11 targets went
on working normally. These two (interrupted 4 min apart) are the incident.

**Issue title:** An agent whose session dies mid-turn stays at STATE=working forever, holds
its mail unread, and `sb cleanup` refuses it — only `--force` clears it

**Issue body:**
When an agent's Claude session ends without `sb done`/`sb block` (observed after
`sb tell --interrupt`, but the cause of the death is not the point), its store row keeps
`state='working'` for as long as herdr still lists its pane. Nothing moves it: `gone` is
only inferred when herdr drops the pane, which can be hours later. Consequences, all
observed in the live store on 2026-08-14 for `worker-24` and `researcher-20`:

- `sb cleanup <name>` refuses with "working, not finished — it has not reported an end"
  and never mentions that `--force` is the way through (broker.py:3721-3732).
- Mail addressed to it is never read. `worker-24` had two messages from its parent cleared
  unread by the eventual forced close, 6.5 h after the agent died.
- For the first 45 minutes the board shows it as an ordinary working agent: the stale
  `turn='working'` edge suppresses the STALLED flag until `_forget_turn` fires
  (`status.py:477`, `turn_stale_grace` 1800s + `turn_doubt_grace` 900s).

The 45-min repair works (`turn_forgotten` events at 14:01 for both agents), but it only
clears `agents.turn`; `agents.state` is untouched, so the cleanup gate keeps refusing.
Minimum useful fix is probably to have the refusal name `--force`, and to let a row that is
`stalled`/`turn_doubted` be swept.

**Same-as:** any report about mail queuing forever for an idle agent, or about
`sb status` showing an agent as live after its session ended.

---

## 2026-08-11-043126-a-child-that-sent-two-done-reports

**Verdict:** STILL BROKEN
**Severity:** medium
**Evidence:** by live run in an isolated clone, plus broker.py:631-656. Reproduced exactly:
created a parent and child row, ran `sb done "first summary"` as the child (state → `done`,
message delivered), then ran **one further `sb` command** as the child (`sb inbox`).
`Broker._revive` (broker.py:653) then did `UPDATE agents SET ended_at=NULL,
state='working'`, and the parent's `sb cleanup tri50-child` printed, word for word with the
report, `refused tri50-child: working, not finished — it has not reported an end`. A second
`sb done` then put a second `[done]` row in the parent's inbox.

**Issue title:** A child that runs any `sb` command after `sb done` reverts to
state=working, so its parent's `cleanup` is refused and a second `done` can be sent

**Issue body:**
`Broker.done` sets `state='done'` and `ended_at`, and `Broker._revive` (broker.py:603-656)
reverts any row with a non-NULL `ended_at` back to `state='working'`, `ended_at=NULL` on
the agent's next `sb` command. Reviving a finished agent is deliberate and right — an agent
being asked a follow-up question is working again — but a child that merely runs one more
`sb` command in the same turn after reporting done undoes its own end. What the parent then
sees, and this is the whole protocol's happy path, is: `[done]` in its inbox, and
`sb cleanup <child>` refusing with "working, not finished — it has not reported an end".
There is also no guard against a second `sb done`, so the parent gets the same report twice
(three times in the original filing, each a longer rewrite).
Reproduced live at HEAD. Candidate fixes: refuse or fold a second `done`; or don't revive
on the agent's own commands within the same turn as its `done`; or have `cleanup` treat a
row that has reported `done` at least once as finished.

**Same-as:** `2026-08-11-043254-the-same-done-report-from-one-child-was` (the same bug,
refiled with the delivery-count detail — the refile's `report-bug drop` of this id did not
take).

---

## 2026-08-11-043254-the-same-done-report-from-one-child-was

**Verdict:** STILL BROKEN
**Severity:** medium
**Evidence:** same live run as above — it is the same defect seen from the parent's side.
The triple delivery is one `done` message per `sb done` call (broker.py:3510-3512, no
guard against a repeat), and the "state lags the report" is `_revive` putting the child
back to `working` between them, not a write-ordering race: `put_message` and
`set_state('done')` are two statements apart in the same call, and the parent's refusal in
the report came from a row that had been revived, which is what my run reproduced.

**Issue title:** The same child `done` report is delivered to the parent once per `sb done`
call, with the child back at state=working in between

**Issue body:**
See `2026-08-11-043126` — same root cause, reported from the parent's side. Each `sb done`
writes another `[done]` message to the parent (broker.py:3510-3512); nothing dedupes them
and nothing refuses a repeat. Between the calls the child's own `sb` commands revive it to
`working` (broker.py:653), so a parent that does what it is told — act on the done report
immediately — gets `refused <child>: working, not finished`. The parent has no way to tell
"my child has not finished" from "my child finished and then said something else", and it
reads the same summary two or three times.

**Same-as:** `2026-08-11-043126-a-child-that-sent-two-done-reports`.

---

## 2026-08-09-071134-sb-cleanup-silently-refuses-to-close-a

**Verdict:** FIXED
**Severity:** medium (as filed)
**Evidence:** by reading + live run. `CleanupResult` (broker.py:419-454) carries
`(name, reason)` for every gate that holds a candidate, every gate now exits through
`refuse()` (broker.py:3686-3754), and cli.py:1072-1075 prints them — every reason for a
named agent, `notable` ones for a sweep. Landed in `2ecde1a` (2026-08-09 22:19, after this
07:11 filing) and widened to sweeps in `dd08c49`. Live in a clone: `sb cleanup
still-working stopped` printed
`refused still-working: working, not finished — it has not reported an end` /
`refused stopped: blocked, not finished — …`, and a bare sweep printed the same lines. The
specific case filed — finished agent held by mail nobody can read — is also no longer
merely explained but lifted: `_finished_and_unreachable` (broker.py:4093) lets that row
sweep normally, and `_clear_unreadable_mail` stops the doorbell chasing it.

**Same-as:** `2026-08-09-010647-sb-cleanup-silently-closes-nothing`.

---

## 2026-08-09-010647-sb-cleanup-silently-closes-nothing

**Verdict:** FIXED
**Severity:** medium (as filed)
**Evidence:** by reading + the same live run; same fix as above (`2ecde1a`, `dd08c49`).
The report's two rows map onto two gates that now both speak: `split-fixer` was `working`,
which today prints `refused split-fixer: working, not finished — it has not reported an
end` (reproduced verbatim in the clone against a fabricated `working` row); `board-teardown`
was `done` with undelivered mail, which today either closes — if the agent has finished and
herdr no longer answers to its name (`_finished_and_unreachable`, broker.py:4093) — or is
refused with "unread mail it could still read" (broker.py:3746). Refusal is now always
named and reasoned, which is what was filed. `sb cleanup --json` carries every refusal
including the ones a sweep keeps quiet.

**Same-as:** `2026-08-09-071134-sb-cleanup-silently-refuses-to-close-a`.

---

## 2026-08-09-004626-agent-name-binding-lost-while-the-agent

**Verdict:** FIXED
**Severity:** high (as filed)
**Evidence:** by reading. The cause was switchboard's own `pane report-agent` call —
`Herdr.report_state` (herdr.py:886-912) does not annotate a pane's agent, it *replaces* it,
and one call evicts the name permanently. `block` lost that call in `2fce8cc` (2026-08-10,
"Stop reporting state on a block, which is what cost the agent its name") and `done` in
`14fa06c` (2026-08-10, "Finishing no longer costs an agent its name"). At HEAD there is no
caller of `report_state` anywhere in the tree (`grep -rn '\.report_state('` over
`switchboard/`, `bin/`, `defaults/` finds none) — only docstrings referring to the removed
calls, one of which (broker.py:4415, "`Broker.done` still does") is now stale and wrong.
`_binding_lost` (broker.py:4403) and `unreachable` (broker.py:4442) were added to name the
condition to a sender rather than promise delivery.

Residual, worth stating rather than reopening: if herdr loses a binding for reasons of its
own, a *working* agent is still permanently unreachable and its row is still only closable
with `--force` — `_finished_and_unreachable` only lifts the mail gate for rows in a
finished state. Nothing in switchboard can re-register a name.

**Same-as:** the "mail never announced to an idle agent" companion this report names as
the same root cause (a group-3 report, I cannot see the id).

---

### One observation outside my six

The 043254 filing session ran `sb plugin report-bug drop 2026-08-11-043126-…` from a clone
and the report is still listed today by `sb plugin report-bug list` in this worktree. I did
not chase it; someone should check whether `drop` is repo-scoped while `file` is not, or
whether `drop` failed silently.
