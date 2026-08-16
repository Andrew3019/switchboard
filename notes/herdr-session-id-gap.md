# Why `session_id` goes missing, and how to close it

Read-only investigation. Queried `switchboard`'s store at
`file:/Users/andrew/Code/switchboard/.git/agentflow/state.db?mode=ro`, read
`switchboard/{broker,herdr,hooks,status,store,output,cli}.py` at
`/Users/andrew/Code/switchboard` (current `main`, not this worktree — this worktree has no
newer commits touching these files), and cross-checked against
`~/.claude/projects/<slug>/*.jsonl` transcripts on disk. No state-changing `sb` command was
run against the live fleet.

## 1. When `session_id` is written today

There is exactly **one writer** of `agents.session_id` that ever fires in practice:
`Broker._claim_session` (`broker.py:832-847`). It reads `CLAUDE_CODE_SESSION_ID` from the
process environment and, if the row has a `pane_id` and doesn't already carry that id,
writes it.

`_claim_session` is called from exactly one place: `Broker.whoami()` (`broker.py:587-625`),
on the `HERDR_PANE_ID` fallback branch — i.e. only when the session-id lookup already
failed (`broker.py:598-604` tries `session_id=?` first; `:606-620` falls back to
`pane_id=?` and claims from there). `whoami()` in turn is called by `cli.py:795`
(`me = b.whoami()`) for **every non-`doctor`/`init` `sb` command**, and by
`me = me or self.whoami()` throughout `broker.py` (delegate, tell, inbox, block, done, …).

There is a second writer that looks plausible but is dead in practice:
`store.update_agent(..., session_id=agent.session_id or None, ...)` at `broker.py:3428`,
right after `self.h.start_agent(...)` in the spawn path. `agent.session_id` there is
whatever herdr's `agent start` reply carries — and per the comment at `status.py:830-835`,
checked against every stored reply in this store's event log, herdr's replies **never**
carry one on the installed version (0.8.x). So this line has written `None` every time it
has ever run; the codebase's own comments already say so (`status.py:823-825`,
`broker.py:1148-1153`).

**The upshot: `session_id` is captured on the agent's own first `sb` command, and not one
moment sooner.** Nothing at spawn time knows it. Nothing in the hooks records it either —
`hooks.mark_turn` (`hooks.py:243-269`) resolves the caller the same way (`_agent_row`,
`hooks.py:180-198`, session id then `HERDR_PANE_ID`) to mark a turn edge, but it only calls
`store.set_turn`; it never writes `session_id`. So even a `UserPromptSubmit`/`Stop` hook
firing on an agent's very first turn does not close the gap.

## 2. Why it was missing for `probe-identity` and `wording` — and why "young" is not the story

`probe-identity`: `delegate` (29704) at `1786834290`... then `board_open` (29708), then
nothing at all attributed to the agent until `gone` (29921) 42281 seconds later —
**11.7 hours**. `wording`: `sb_pinned`→`delegate`→`board_open`→`start` all within 4 seconds
of `1786874887`, then **nothing else** until the restart's `gone` ~2043s later. Neither
agent has a single event in the log that required it to run `sb` itself (no `done`,
`block`, `tell`, `restore`, `message`, …) between spawn and death.

That is consistent with a race, but the store shows it is **not** narrowly a race. I
queried every agent currently holding an empty `session_id` (34 of 488 rows,
`SELECT session_id IS NULL OR session_id='' … GROUP BY`) and looked at lifespan
(`ended_at - created_at`):

```
probe-identity   42281s (11.7h)  done→failed at cleanup
recheck-2/3      38059s/38066s   done, forced cleanup
researcher-20    23183s          failed
worker-24        24021s          done (forced cleanup_forced_live)
main-13          8035s           failed
split-fix-lead   13484s          failed
mail-truth        3722s          done
wm-spawn-claim    3160s          done
```

Several of these ran for **hours**, some with dozens of events in the log — but every one
of those events is a *parent-side* action (`read_output`, `interrupt`, `cleanup_refused`,
`cleanup_forced_live`) or a *reconciler-side* verdict (`gone`), never an event that could
only exist because the agent itself called `sb`. `worker-24`/`researcher-20` (`broker.py`
events 24871-26442) show the concrete shape: spawned, interrupted mid-task by the human,
read repeatedly by the parent, and eventually force-closed — never once running `sb done`,
`sb block`, or anything else. `recheck-2`/`recheck-3` are starker: spawned, then silence,
then forced cleanup 10.5 hours later.

So the real population is: **any agent that goes its entire life without running one `sb`
command of its own.** That includes agents killed in the first seconds (the literal race
Andrew described) but also agents that ran for hours doing real tool-call work and simply
never happened to invoke `sb` — because their task didn't require reporting back yet, or
because they were interrupted/superseded before reaching their first `sb done`/`sb block`.
**I am a live example of the same thing right now**: as of this writing, agent
`researcher-57` (me) has an empty `session_id` in the store — `researcher-55` and
`researcher-56`, my siblings on this same task, already claimed theirs (they ran `sb`
verbs already); I have not, because nothing before this report required it. Role does not
predict it either — `researcher-20`, `orchestrator`-role `main-13`, `worker`-role
`worker-24`, `lead`-role rows all appear in the empty-`session_id` set.

`wording` is the sharper case of the same mechanism: it is a **root dispatcher**
(`sb start`), so its very first turn is what should establish it, and even that never
happened before the restart killed it 7 minutes in — the agent's Claude Code process
plausibly never got as far as running any `sb` command at all (no `turn_start` event for
it either).

## 3. How wide the window is

Not a fixed millisecond window — an **open-ended** one, bounded only by "when does this
agent first run `sb`". The two numbers the code itself already derives and relies on for
this exact fact:

- `SPAWN_GRACE` (`status.py:182-195`) ≈ 287s (3 spawn attempts × 90s + backoff) — how long
  a session-id-less row is read as "still claiming a pane", not gone.
- `STALL_GRACE` (`status.py:227-231`) — the delivery retry's own worst case — how long a
  session-id-less row is read as "hasn't taken its first turn yet", not stalled.

Both constants exist **because** the codebase already treats "no session id yet" as
indistinguishable from "hasn't started" for as long as those windows run (see the extended
comment at `status.py:205-213`: "the one durable trace an agent leaves of having run is its
`session_id`... before it, `idle` and `not started yet` are the same reading"). Past those
windows the code has no further story — an agent can stay session-id-less indefinitely
(34/488 = ~7% of all rows in this store right now), and nothing currently notices or
recovers it.

## 4. Can the id be recovered after the fact from `~/.claude/projects/…`?

Traced concretely for `probe-identity`. Its `cwd` is
`/Users/andrew/.herdr/worktrees/switchboard/codex-support` — a worktree it **shares with
its parent `codex-support` and every other agent delegated into that same workspace**
(`delegate`, unlike `fork`, does not create a new worktree). The transcript bucket for that
cwd (`~/.claude/projects/-Users-andrew--herdr-worktrees-switchboard-codex-support/`)
currently holds **7 separate `.jsonl` files**, several ending within a minute of each
other. One (`da72b692-…`) ends at 2026-08-16 03:36:19 local, 8 seconds after
`probe-identity`'s `gone` event (03:36:11) — a tempting match — but its first message
timestamp is 2026-08-15 15:24:30, **27 minutes before `probe-identity` was even created**
(15:51:30). That file is almost certainly `codex-support`'s own long-running transcript,
not `probe-identity`'s: matching by cwd + closest-end-time alone would have attributed the
parent's session to the child.

**Verdict: cwd + time proximity is a guess, not a sound recovery route**, precisely because
`delegate` shares one cwd across a parent and all its non-forked children, and multiple
agents in the same workspace write to the same directory concurrently. It gets worse the
busier the workspace and the longer both sessions run — nothing in the `.jsonl` filenames
or directory structure ties a file to a specific `sb` agent name after the fact.

The one thing that WOULD disambiguate reliably is **content**, not time: does a specific
file contain the literal first-task text this agent was given? That is a strictly stronger
signal than proximity, and the codebase already has it (see §5) — it is just not being
used to persist anything.

## 5. Closing the window at the source

Options weighed:

- **Agent self-reports its session id as first act.** Costs nothing to build (a `sb`
  invocation already resolves and would claim it), but does not cover the actual failure
  population from §2: agents that are killed, interrupted, or superseded *before* they run
  it — which is most of the 34 rows found, not a handful.
- **Read it from the provider at spawn (`agent start`'s reply).** Already wired
  (`broker.py:3428`) and already dead — herdr's reply never carries one on the installed
  version. Costs nothing further to keep, closes nothing until herdr changes.
- **Poll for it.** Requires guessing which of possibly-several files in the same cwd
  bucket is this agent's, with no name-bearing signal to poll on beyond content — same
  ambiguity as §4, just automated.
- **Match by content at spawn, and persist what already gets found.** `output.task_arrived`
  (`output.py:138-179`) already does the hard part: it is called as `deliver`'s `proof`
  (`broker.py:3464-3467`, `output.task_arrived(str(where), task, since=since)`) to confirm
  the spawn's first task landed, by scanning every `*.jsonl` in the cwd's transcript
  directory for one written since `sent` whose tail contains the literal task text. It
  already resolves the ambiguity in §4 the right way (by content, not by time), it already
  runs on every spawn, and today it **throws its answer away** — it returns `True`/`False`
  and never reports which file matched.

**Recommendation: the fourth option.** It is the only one that covers the actual failure
population (closes the gap *before* the agent has run anything, including agents later
killed or interrupted), costs a small, local change, and reuses machinery already proven
correct by `deliver`'s own test suite rather than adding new guesswork.

**The decisive reason:** every other option either does nothing for an agent that never
gets to run `sb` (self-report, provider-read), or repeats the exact ambiguity §4 already
demonstrated is unsound (any time-based poll). Content-matching at spawn is the only
approach that is both *early enough* to catch the killed-early cases and *precise enough*
to not misattribute a shared-cwd sibling's transcript.

**What it costs if this is wrong:** if herdr ever starts reporting a real session id itself
(the `status.py:833-835` comment already flags this as a live hole to watch for), this
becomes redundant work done on every spawn — one extra directory scan per spawn, cheap but
pointless. If `task_arrived`'s content-match ever produces a false positive (two agents
spawned into the same cwd within the same second with textually-identical first tasks —
not observed in this store, but not impossible with an identical `spawn.start_task`
placeholder for two agents spawned back-to-back with no task), the row could claim the
wrong session id. That risk is bounded and checkable: verify uniqueness of the matched
`(cwd, text, since-window)` before writing, same as `task_arrived` already assumes for
its own purposes.

### The concrete change

1. `switchboard/output.py`: add a sibling to `task_arrived` — e.g.
   `matched_transcript(cwd, text, *, since) -> Optional[str]` — same scan as
   `task_arrived` (`output.py:156-178`) but returning the matching file's session id
   (`f.stem`) instead of `True`, and `None` instead of `False`. (`task_arrived` itself can
   become a one-line wrapper: `matched_transcript(...) is not None`, to avoid duplicating
   the scan.)
2. `switchboard/broker.py`, in `_spawn` right after `self.h.deliver(...)` returns
   successfully (after line 3467, before the fall-through `return name` at ~3504):
   if `store.get_agent(self.db, name)["session_id"]` is still empty, call
   `output.matched_transcript(str(where), task, since=sent)` (same `where`/`task`/`sent`
   already in scope from the `deliver` call above) and, if it returns an id,
   `store.update_agent(self.db, name, session_id=sid)`.
3. Because `_top` (`broker.py:1183-1191`, the `sb start` path that produced `wording`)
   calls `self.delegate(...)` for its first task, this one change covers both root
   dispatchers and ordinary `sb delegate` children — no second call site needed.

This does not help an agent whose *first* task delivery genuinely could not be confirmed
at all (`deliver` raised and `_took_a_turn` found nothing) — that is already the
`task_undelivered`/`GONE_STATE` path today, and correctly so: there is no transcript to
match against.

### Tests to pin it

1. **Unit, `output.matched_transcript`**: given a fake transcript directory with one file
   containing the sent text after `since` and one file containing unrelated text (or the
   same text before `since`), it returns the first file's stem and not the second's —
   mirrors the existing `task_arrived` fixture setup, just asserting on the id instead of
   the bool.
2. **Broker-level, spawn writes session_id from the matched transcript**: spawn (via the
   test harness's fake `herdr`/fake transcript writer already used for `deliver`/
   `task_arrived` tests) an agent whose `agent.session_id` comes back empty from herdr (the
   real-world case), confirm the row's `session_id` is populated after `delegate`/`_top`
   returns, sourced from the transcript match rather than herdr's reply.
3. **Regression, shared-cwd ambiguity does not regress**: two agents delegated into the
   *same* cwd with *different* first-task text — each ends up with its own, correct
   `session_id`, not each other's. (This is the `probe-identity`/`codex-support` shape
   from §4, made deterministic in a fixture instead of relying on the real transcript
   directory.)
