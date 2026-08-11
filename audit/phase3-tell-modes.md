# Phase 3 — the `tell` cluster (3.1, 3.3, 3.2, 3.6)

Branch `phase3-tell-modes`, based on `phase3.5a-needs-reply` (`c7f43fa`).

The pass/fail tests below were written **before any code was changed**, from
`BUILD-PLAN.md`'s pass lines, `audit/phase3-scope.md`, and `DESIGN-TRUTH.md:236-247`.
Results are recorded against them at the bottom, filled in as each item lands.

The open question that gated 3.1 is settled by `audit/phase3-delivery-primitive.md`
(branch `probe-delivery-primitive`): `agent prompt` **queues** — the message lands at the
recipient's next tool-call boundary with the in-flight call completing, and cancels
nothing. So *next turn* is built by calling the primitive the busy-gate currently refuses
to call, with no escape keypress and no cancel wrapper.

---

## Tests

### 3.1 — three delivery modes on `sb tell`

**T1.1 (live, primary) — next turn reaches a busy agent at its next boundary.**
Give an agent one long single tool call (a 90s `Bash` sleep loop writing timestamps).
Part-way through, `sb tell <agent> "..."` with no mode flag.
*Pass:* the tool call runs to completion (its own log shows every line), the agent reports
that the text arrived attached to that call's result, and delivery happened at send time
(`sb tell` reports no "will be rung when free", the store row has `delivered_at` set).
*Fail:* the call is cut short (interrupt without cancellation semantics), or delivery is
deferred until the whole turn ends (today's only behaviour).

**T1.2 (live) — when idle still defers.** Same setup, `sb tell --when-idle`.
*Pass:* `sb tell` reports the target mid-turn, the store row is undelivered while the tool
call runs, and the doorbell lands only after the agent's turn ends.
*Fail:* it lands mid-turn (mode not honoured).

**T1.3 (live) — interrupt still cancels.** Same setup, `sb tell --interrupt`.
*Pass:* the in-flight tool call is abandoned (its log stops short of 90 lines) and the
agent reads the cancel-worded body inline.
*Fail:* the loop runs to completion, i.e. the escape keypress was lost with the verb.

**T1.4 (automated) — `sb done`'s parent poke stays *when idle*.** DESIGN-TRUTH:220-224.
*Pass:* a `done` whose parent is busy does not ring; it is deferred and flushed later.

**T1.5 (automated) — a blocked agent's mail is still held (3.4 not regressed).**
*Pass:* a default-mode `tell` to a blocked agent does not ring and does not clear the
block; the human's own `tell` still does.

### 3.3 — every sb message carries `[sb: from <name>]`

**T3.1 (automated) — the doorbell names its sender.** A `tell` from `w1` to `w2` rings
text containing `[sb: from w1]`. The `done` poke to a parent names the child. A human's
`tell` names `human`.

**T3.2 (automated) — the inline interrupt body carries the same tag**, and so does
`sb inbox`'s own output line — the same `[sb: from <name>]` shape, not a second spelling.

**T3.3 (live) — an agent receiving mail sees the tag** in its pane and in `sb inbox`.

### 3.2 — delete the `sb interrupt` verb

**T2.1 (automated) — `sb interrupt w "stop"` no longer parses** (argparse error, exit 2).

**T2.2 (live) — the capability survives**: `sb tell --interrupt` still cancels a running
tool call (this is T1.3, re-run after the verb is gone).

### 3.6 — remove `sb ask`

**T6.1 (automated) — `sb ask w "q?"` no longer parses**, and `Broker.ask` no longer
exists.

**T6.2 (grep) — no shipped prompt mentions it**: `grep -rn "sb ask" defaults/` is empty.

---

## Results

*Filled in as each item lands. This file's git history is the record of the order the
tests were written in versus when the code changed.*

### 3.1 + 3.3 — PASS

**Automated.** Four new tests in `tests/test_broker.py`
(`test_the_default_mode_rings_a_busy_agent_and_cancels_nothing`,
`test_a_blocked_agent_holds_its_mail_in_every_mode_but_interrupt`,
`test_every_line_sb_puts_in_a_pane_names_who_sent_it`,
`test_the_inbox_spells_the_tag_the_same_way_the_doorbell_does`) cover T1.4/T1.5 and
T3.1/T3.2. Five existing tests changed because the default mode changed under them — four
now pass `mode=WHEN_IDLE` to keep testing the deferral they were written for, and one
asserts the reworded reply prompt. Whole suite at this commit: 1122 passed;
1108 after 3.6 deleted `sb ask`'s own tests.

**Live.** Isolated `git clone` of this branch at
`<scratchpad>/tellclone`, driven throughout by that clone's own `./bin/sb`. Every spawn
spawn I made used `--no-board --no-focus`, so no collector ran for any of these trials
(`sb doctor` in the clone confirmed its own store under `<clone>/.git/agentflow/state.db`
and "no collector") — one did start later, in the delegate trial under 3.6, and Teardown
below says what became of it. One
subject per trial, each running a single 90-second `Bash` loop appending timestamps to a
`/tmp` log file watched from outside the agent — that log, not the agent's self-report, is
the authority on whether the call was cut short.

| | T1.1 default (next turn), `subject-a` | T1.2 `--when-idle`, `subject-c` | T1.3 `--interrupt`, `subject-d` |
|---|---|---|---|
| sent | 02:22:23, 18 lines in | 02:30:40, 10 lines in | 02:33:05, 9 lines in |
| loop's own log | **90/90**, 02:22:06→02:23:36 | **90/90** | **stopped at 9** and never grew again |
| `sb tell` said | `sent to subject-a` | `subject-c mid-turn or blocked — will be rung when free` | `sent to subject-d` |
| `delivered_at` | set at send | NULL through the whole loop (18→90 lines), set at 02:32:21 once the turn ended | set at send |
| the agent's own account | "no awareness of any message while the command was running… appeared only when the Bash call's result came back" | "nothing became visible to me during the call"; poked after it stopped | "the tool call returning as rejected, and immediately after it the interrupt text" |

T3.3 passed in all three: `subject-a`'s pane read
`[sb: from human] You have mail. Run: sb inbox`, its `sb inbox` read
`[1] [sb: from human] T1.1 default mode probe…` (same tag, same shape), and `subject-d`
read the interrupt body inline as `[sb: from human] [INTERRUPT — stop now] …`.

One trial is recorded above and not counted: an earlier `--when-idle` subject (`subject-b`)
held its mail correctly for the whole loop but then ended its turn with `sb done`, so the
held message was written off as unreadable rather than rung — existing, correct behaviour
for a finished agent, but it proves the hold and not the release, which is why T1.2 was
re-run with a subject instructed to go idle without finishing.

### 3.2 — PASS

T2.1: `sb interrupt subject-x "stop"` in the clone exits 2 with an argparse
`invalid choice: 'interrupt'`, and the verb is absent from the usage line. Pinned by
`test_the_interrupt_verb_is_gone_and_the_mode_replaces_it`.

T2.2, the half that matters: with the verb deleted, `subject-e` was given the same
90-second single tool call and interrupted through `sb tell --interrupt` at 11 lines in.
Its log stopped at **11/90** and never grew again; the agent read
`[sb: from human] [INTERRUPT — stop now] …` inline and confirmed `sb inbox` was empty,
i.e. the text travelled inline rather than as mail. The capability survived the deletion.

### 3.6 — PASS

T6.1: `sb ask w1 "q?"` in the clone exits 2 with `invalid choice: 'ask'`; `Broker.ask` no
longer exists (both pinned by `test_the_ask_verb_is_gone`). T6.2:
`grep -rn "sb ask" defaults/` is empty — `protocol.md` now points at
`tell --needs-reply` instead.

**One extra live trial, unasked for but worth the two minutes**, because 3.6 removed a
method the whole `tell` path shared: `lead-a` was told to delegate a trivial task and end
its turn. The child reported with `sb done`, the parent was woken by the held when-idle
poke and read it as
`[sb: from worker-1] A child finished. Run: sb inbox…`, then reported itself. Delegate →
done → when-idle poke → inbox still works end to end with all four items landed.

### Teardown

Every subject and lead closed with `sb cleanup` (`sb status` in the clone showed
`0 alive`). One collector had been started inside the clone by the delegate in that last
trial; it was confirmed to hold the clone's own `collector.lock` and killed by its exact
pid — never an unscoped `pkill`, and the live fleet's collector was checked to still be
running afterwards. The child's worktree under `~/.herdr/worktrees/tellclone/` was removed
with `git worktree remove` and the now-empty parent directory deleted. The clone itself and
the `/tmp/sb-tellprobe-*.log` files are gone.

### Not proven

- **Multi-message ordering while busy.** Two next-turn tells sent before the first is
  consumed — whether they arrive in order, coalesce, or one is lost — was not tested here
  or in the primitive probe, and nothing in this work makes it less likely to matter now
  that the default reaches a busy agent.
- **Next turn against a very short tool call, or a nested subagent's own tool calls.** All
  trials used one long `Bash` call, which is the shape that distinguishes the modes at all.
- **`--interrupt` against an idle rather than busy agent** — the escape keypress should be
  harmless, but it was not run.
- **The reworded `--needs-reply` prompt** was not re-proven live; it is a text change to a
  path 3.5a already proved, and the wording is pinned by the existing inbox test.
- Automated tests drive a fake herdr that records `prompt`/`send_keys` rather than running
  Claude, so they pin which primitive each mode calls and in what order — never that the
  model queued the text. Only the live trials show that, and the fake was not grown to
  claim otherwise.
- `sb ask`'s removal left the store's `kind='ask'` rows, `reply_to` column, `pending_ask`
  and `sb inspect`'s rendering of unanswered asks in place, so an old store stays readable.
  Nothing writes those rows any more; that dead-but-harmless surface is not this item's to
  delete and is flagged rather than removed.

