# AUDIT GROUP 2 — MESSAGING AND DELIVERY

Audited against `DESIGN-TRUTH.md` (the only trusted document) in the worktree
`/Users/andrew/.herdr/worktrees/switchboard/worker-2` @ `a9dd319`, branch `worker-2`.

**Branch skew.** All three auditors independently checked this. The `sb` on PATH resolves to a
different checkout (`/Users/andrew/Code/switchboard` @ `caa6d20`, main, clean), but
`git diff origin/main..HEAD -- switchboard/ bin/ defaults/` is **empty** — the audited code is
byte-identical to main. Nothing in this report is "already fixed on main", and live runs of `sb`
exercise exactly the code quoted.

Read-only throughout: no code or docs changed, no mutating `sb` calls, no simulation agents spawned.

## Verdict counts

The group's 7 design entries decompose into 10 separately-verdictable claims.

| Verdict | Count |
|---|---|
| SATISFIED | 1 |
| PARTIAL | 6 |
| BROKEN | 3 |
| UNVERIFIED | 0 |

| # | Claim | Verdict |
|---|---|---|
| 1 | `sb tell` mode — **next turn** (default) | BROKEN |
| 2 | `sb tell` mode — **when idle** (incl. "a blocked agent is not idle") | PARTIAL |
| 3 | `sb tell` mode — **interrupt** | PARTIAL |
| 4 | `sb done` keeps the agent open | **SATISFIED** |
| 5 | `sb done` always uses when-idle delivery | PARTIAL |
| 6 | "There is `tell` only. No agent ever waits on another agent." + `--needs-reply` | BROKEN |
| 7 | `sb tell` is for agents only, both ways round | PARTIAL |
| 8 | `sb inbox --peek` stays; a read message is never brought up again | PARTIAL |
| 9 | Every sb message is prefixed as an sb message | BROKEN |
| 10 | How herdr actually talks to Claude | PARTIAL |

## The three sharpest gaps

**1. `sb tell` has no delivery modes at all — the entire three-mode design is unbuilt.**
`sb tell` takes no mode flag (`cli.py:148-151`; confirmed live), `Broker.tell` has no mode
parameter (`broker.py:2670-2711`), and `_ring` (`broker.py:3386-3438`) implements exactly one
behaviour: hold the doorbell while the target is mid-turn. That is a rough approximation of
when-idle. "Next turn" does not exist and, on the current transport, cannot: `herdr agent prompt`
**interleaves rather than queues** (`herdr.py:457-471`, with a live re-verification in that
docstring — a poke handled at +13s into a 63s turn). Interrupt exists but as its own verb whose
docstring argues it is "Not a variant of `tell`" (`broker.py:3187`), directly contradicting
DESIGN-TRUTH:287.

**2. A blocked agent is not protected — mail cancels the block and buries the human's answer.**
The design says when-idle mail is held until a block is answered. In code, `block` deliberately
pushes herdr state `idle` (`broker.py:2902`), so `_busy` reports the agent free; `_ring` then
proceeds and `_unblock_if_needed` (`broker.py:3440-3462`) *actively* flips it to `working` before
prompting. Any sibling's unrelated `tell` therefore lands instantly on a blocked agent, cancels
its block, and drops it out of `sb status --needs-me`. Proven with a probe against the repo's own
test fakes. The existing test protection covers only already-read mail, not a new `tell`.

**3. Nothing sb puts on the wire is marked as coming from sb.**
`_ring` passes text untouched to `herdr agent prompt` (`broker.py:3431` → `herdr.py:471`), and the
doorbell strings in `defaults/prompts.toml:63,71,81` are bare sentences ("You have mail. Run: sb
inbox"). A spawned child's first task is equally raw (`broker.py:2646`). No sender name reaches the
chat box on any path. The prefixing that does exist is inside `sb inbox`'s tool output
(`cli.py:778`) and the `[done]` marker readers strip — neither is the shared channel the entry is
about. Live proof from this audit: a child's first turn arrived as its task line fused directly to
the doorbell with no separator and no marker.

## Two contradictions that need Andrew, not a build task

- **Does a prompt to a working Claude queue or interleave?** DESIGN-TRUTH:82-88 says Claude's own
  system queues it and delivers it next turn. `herdr.py:460-468` asserts the opposite and says so
  in capitals, and the whole defer-while-busy path exists because of that belief. Both cannot hold.
- **How does Andrew answer a block, if not with `sb tell`?** The design says `tell` is agents-only
  and Andrew does not use it, but no other route exists and the code hands him `tell` in six
  places. Removing his use of it needs a replacement decision, not a deletion.

## What went wrong with the process

All three auditors were spawned with their task left sitting **unsent** in the prompt box — they
sat idle for nine minutes until nudged with a follow-up `tell`, which pushed the unsent text
through. The orchestrator for this group hit the identical glitch on its own spawn. This is a real
spawn-delivery bug, and it is corroborating evidence for gaps 1 and 3 above.

---

The three per-slice reports follow verbatim, with their own file:line evidence and per-entry gap
lists (each gap line is written to be directly usable as a build task).

---

# AUDIT 2A — DELIVERY MODES — FINDINGS

Audited tree: `/Users/andrew/.herdr/worktrees/switchboard/worker-2` @ `a9dd319` (branch `worker-2`).

**Branch skew check:** `sb` on PATH is `/Users/andrew/.local/bin/sb` → symlink →
`/Users/andrew/Code/switchboard/bin/sb` (main checkout @ `caa6d20`, clean). But
`git diff --stat origin/main HEAD -- switchboard/ bin/ defaults/` is EMPTY — the code under audit
is byte-identical to `main`. So nothing below is "already fixed on main", and the installed `sb`
behaves as the code I read.

Verification: read the source, plus a live probe run against the repo's own test fakes
(scratchpad only, no repo change, no agents spawned) — see "Probe" at the end.

| # | Entry | Verdict |
|---|---|---|
| 1a | tell — **next turn** (default) | **BROKEN** |
| 1b | tell — **when idle** | **PARTIAL** |
| 1c | tell — **interrupt** | **PARTIAL** |
| 2a | `sb done` keeps the agent open | **SATISFIED** |
| 2b | `sb done` always uses **when idle** | **PARTIAL** |

Counts: SATISFIED 1, PARTIAL 3, BROKEN 1, UNVERIFIED 0.

---

## Cross-cutting fact, established first

**There are no delivery modes in the code. There is one delivery behaviour, and it is not
selectable.**

- `sb tell` takes no mode flag: `cli.py:148-151` (`who`, `message`, hidden `--re`). Confirmed live:
  `sb tell --help` → `usage: sb tell [-h] [--json] who [who ...] message`.
- `Broker.tell` (`broker.py:2670-2711`) has no mode parameter; it writes the row and calls
  `self._ring(t, ...)` (`broker.py:2710`) unconditionally.
- `_ring` (`broker.py:3386-3438`) is the single delivery path. It **holds the doorbell back while
  the target is mid-turn** (`broker.py:3426-3428`: `if not force and self._busy(who): log
  ring_deferred; return False`).

So the only implemented behaviour is a defer-while-busy one — i.e. an approximation of **when
idle**. "Next turn" does not exist as a distinct mode, and neither does an explicit "when idle"
mode; `interrupt` exists only as its own top-level verb.

---

## 1a. **next turn** (the default) — BROKEN

Design: doorbell sent **instantly**; the agent's own system queues it and delivers at its next
turn boundary; **waits for nothing, cancels nothing**.

Code does the opposite of "instantly, waits for nothing":

- `broker.py:3426-3428` — a `tell` to a WORKING agent is **not** sent. It logs `ring_deferred` and
  returns `False`. The message sits with `delivered_at IS NULL` (`store.py:1336`) until some later
  `flush_pending`.
- `cli.py:747-761` — the CLI's own success text admits it: `"(… mid-turn — will be rung when
  free)"`.
- `tests/test_broker.py:530-537` — `test_the_doorbell_is_held_back_while_the_target_is_mid_turn`
  asserts exactly this: `self.h.prompts == []` after a `tell` to a working agent.

And the design premise behind "next turn" is contradicted by a live-verified code note:

- `herdr.py:457-471` (`Herdr.prompt`) — **"This INTERLEAVES. It does not queue."** With a
  re-verification note: on a genuine 60s multi-step turn the poke was handled at +13s while the
  task ran to +63s. DESIGN-TRUTH:82-88 ("a message is queued by Claude's own system and delivered
  on the next turn") describes typing into the chat box; `agent prompt`, which is what `_ring`
  actually uses, is **not** that channel. So as written, the default mode cannot be built on
  `_ring` at all without changing the transport.

Gaps (each one a build task):

- `sb tell` has no `--next-turn` / mode flag; there is no way to ask for this mode. (`cli.py:148`)
- `_ring` refuses to send to a WORKING target, so the default is defer, not next-turn.
  (`broker.py:3426`)
- The transport used for the doorbell (`herdr agent prompt`) interleaves mid-turn rather than
  queueing to the turn boundary, so "sent instantly, cancels nothing" is not achievable through it
  — a next-turn mode needs a different wire (the chat-box paste path DESIGN-TRUTH:82-88 describes)
  or an explicit decision that deferral is what next-turn means. (`herdr.py:460-466`)

## 1b. **when idle** — PARTIAL

Satisfied parts, with evidence:

- sb does hold the doorbell and send it once the target stops working: `broker.py:3426-3428` holds;
  `broker.py:3304-3352` (`flush_pending`) re-rings anyone with `store.unseen` mail who is not busy.
  Test: `tests/test_broker.py:538-546`.
- **"herdr's status is the more accurate place to derive it from"** — SATISFIED. Idleness is taken
  from herdr, not from the store: `_busy` (`broker.py:3296-3302`) reads `_agent_states()`
  (`broker.py:3230-3245`), which is `herdr agent list`.

Gaps:

- **Not selectable.** No `--when-idle` flag; it is simply what every `tell` does. (`cli.py:148`,
  `broker.py:2670`)
- **"A blocked agent is not idle … when-idle mail is HELD until its block is answered" — this is
  BROKEN, and it is the sharpest finding in the audit.** `block` deliberately pushes herdr state
  `idle`, not `blocked` (`broker.py:2902` with the reasoning at `2892-2901`). `_busy` therefore
  returns False for a blocked agent, `_ring` proceeds, and `_unblock_if_needed`
  (`broker.py:3440-3462`) *actively* flips the agent to `working` in both herdr and the store
  before prompting. Net effect: unrelated mail from any sibling lands on a blocked agent
  immediately, cancels its block, and removes it from `sb status --needs-me` — so the human's
  answer, when it comes, is buried under exactly the mail the design says must be held. Proven by
  probe (below). The existing protection (`tests/test_broker.py:566-593`,
  `test_a_stale_doorbell_does_not_cancel_a_block`) only covers *already-read* mail via the
  `unseen`-not-`undelivered` predicate; it does not cover a **new** `tell`.
- **"No more turns, and if we waited an hour there would be no new activity" is not the test used.**
  `_busy` is an instantaneous `state == "working"` check (`broker.py:3302`) with no dwell time — an
  agent between two tool calls, or momentarily reported idle, counts as idle.
- **Unknown reads as idle.** `_agent_states()` returns `None` when herdr cannot be asked
  (`broker.py:3243-3245`) and `_busy` treats that as not-busy (`broker.py:3302`, docstring
  `3299-3301`). During a herdr outage, when-idle mail is injected mid-turn — the one thing the mode
  exists to prevent.
- **The held doorbell has no autonomous trigger.** `flush_pending` is called only from
  `cli.py:585` (start of any `sb` command) and `broker.py:2791` (inside a blocking `ask`). Nothing
  else — no daemon, no board loop (grep for `flush_pending` finds no other caller). If no other
  agent or human runs an `sb` command, held mail never lands, however idle the target is. The
  docstring concedes this: "This is the stand-in for an events daemon" (`broker.py:3325`).

## 1c. **interrupt** — PARTIAL

The mechanism matches the description; its shape does not.

Satisfied:

- Injected mid-turn cancelling what the agent was doing: `broker.py:3214-3217` sends `esc` via
  `herdr.send_keys` (`herdr.py:491-499`, the only way to cancel a turn), sleeps `INTERRUPT_SETTLE`
  (`broker.py:107`) so the cancel lands, then `_ring(..., force=True)` (`broker.py:3224`) which
  bypasses the busy hold (`broker.py:3426`) and carries the text inline. Test:
  `tests/test_broker.py:600-606`.
- A failed forced ring raises `Undeliverable` rather than silently deferring
  (`broker.py:3434-3435`), and the row is marked read only after delivery (`broker.py:3225`,
  test at `tests/test_broker.py:621-634`).

Gap:

- **It is a separate verb, not a delivery mode of `tell`.** `cli.py:288-290` defines `sb interrupt
  <name> <text>`; dispatch at `cli.py:897-899`; `Broker.interrupt` is its own method
  (`broker.py:3184`) whose docstring states outright "Not a variant of `tell`". DESIGN-TRUTH:287
  cuts this explicitly: "**`sb interrupt` as a verb.** Interrupting is a delivery mode of `tell`."
  Build task: fold it into `sb tell --interrupt` (keeping `sb interrupt` as an alias at most).
- Minor: `Broker.interrupt`'s docstring calls it "Human-facing; emergencies only", a restriction
  the design entry does not state either way. Flagging, not scoring.

## 2a. `sb done` keeps the agent open — SATISFIED

- `Broker.done` (`broker.py:2830-2869`) writes a message to the parent (`2856-2857`), sets store
  state `done` (`2858`), pushes herdr `idle` (`2859` — herdr has no `done`; `herdr.py:570-571`),
  logs, and rings the parent. **It closes nothing**: no `close_pane`, no `cleanup` call anywhere in
  the method.
- The CLI branch (`cli.py:783-792`) only prints and returns 0.
- Closing is a separate decision made by the orchestrator via `cleanup` (`broker.py:2915+`), and
  `done` explicitly keeps a done-with-live-children agent reachable (`broker.py:2839-2848`,
  `live_descendants` gate).
- A done agent stays a valid mail target while its pane exists:
  `tests/test_broker.py:659-666`, `689-696`.

## 2b. `sb done` always uses the **when idle** delivery mode — PARTIAL

- The parent's summons goes through the ordinary deferred path: `broker.py:2868` calls
  `self._ring(parent, self._say("notify.child_done"))` — no `force`, so `broker.py:3426` holds it
  while the parent is mid-turn. In effect it is when-idle, so the letter of the entry holds.
- But only *by default, not by choice*: there is no mode to select (same gap as 1b), so "always
  uses when idle" is true only because no other mode exists.

Gap — **"the held doorbell fires the moment the top is idle, so it is woken rather than
monitoring" is not what happens:**

- If the parent is idle at the moment the child calls `done`, the ring lands immediately and the
  entry holds.
- If the parent is mid-turn, the ring is deferred and there is **no timer, no daemon and no
  watcher** that fires when it goes idle. It fires only when some *other* process runs an `sb`
  command (`cli.py:585`) — which, for a top orchestrator whose last child just finished and whose
  fleet has therefore gone quiet, may be never. In that case the top is not woken and must poll,
  which is precisely what the entry says it should not have to do.
- Second-order: the child that just ran `sb done` cannot rescue this — its own `flush_pending` runs
  at the *start* of the `done` command (`cli.py:585`), before the message exists.
- Also inherits 1b's blocked-agent bug: a `done` from a child lands on and silently unblocks a
  parent that had stopped to ask the human.

---

## Probe (how the blocked-agent finding was proven)

Ran in the scratchpad against the repo's own `tests/test_broker.py` fakes (no repo write, no
agents spawned, no `sb` mutation):

```
create agent "w" (pane w1:p1); b.block("which branch?", me="w")
herdr says w is "idle"   # because broker.py:2902 pushes IDLE, not blocked
b.tell(["w"], "unrelated mail from a sibling", me="other")
→ PROMPTS:     [('w', 'You have mail. Run: sb inbox')]     # rung immediately
→ STATE AFTER: working                                     # block cancelled
→ UNDELIVERED: []                                          # nothing held
```

Expected per DESIGN-TRUTH:224-225: no prompt, state stays `blocked`, message held.

The repo's own 150 broker tests all pass on this tree, so none of the above is a regression — it is
what the code was built to do.

## Process notes

- Nothing went wrong with the tooling. `sb inbox`, `sb tell --help`, `sb done --help` all worked;
  no mutating `sb` command was run and no `audit-sim-*` agents were needed.
- One out-of-scope observation, reported not fixed (other agents own these entries): `sb ask`
  exists in code (`cli.py:140-146`, `broker.py:2713`) and blocks the caller, while DESIGN-TRUTH:283
  cuts it — "No agent waits on another agent." Same shape of finding as 1c.
# AUDIT 2B — FINDINGS: tell-only, and who tell is for

Tree audited: `/Users/andrew/.herdr/worktrees/switchboard/worker-2` @ `a9dd319` (branch `worker-2`).
`git diff origin/main..HEAD -- switchboard/cli.py switchboard/broker.py defaults/protocol.md`
is **empty** — local `main` (`caa6d20`) has the same code, so nothing below is "already fixed on main".
The `sb` on PATH is `/Users/andrew/Code/switchboard/bin/sb` (a different checkout); every run below
was done with the worktree's own `./bin/sb`, and its `--help` output matches this tree.

Verdicts: **0 SATISFIED · 1 PARTIAL · 1 BROKEN**

---

## Entry 1 — "There is `tell` only. No agent ever waits on another agent." (DESIGN-TRUTH.md:212–214)
Related confirmed rejections: **`sb ask`** (283), **`sb wait`** (285), **`sb interrupt` as a verb** (287).

### Verdict: BROKEN

All three rejected verbs are present, wired, documented and shipped to agents.

**`ask` — a blocking agent-to-agent verb, exactly what the entry rejects**
- `switchboard/cli.py:139` `a = cmd("ask", help="send a question and WAIT for the answer")`
- `switchboard/cli.py:370-373` validation branch; `switchboard/cli.py:739-740` `b.ask(...)`
- `switchboard/broker.py:2713` `def ask(...)` — its docstring at 2718-2721 says "Send and block
  until every target answers … For AGENTS only, and it is the only blocking verb."
- Blocking loop: `broker.py:2757-2789` (`while time.time() < deadline: … time.sleep(poll)`)
- Config for it: `broker.py:101-103` `ASK_TIMEOUT` / `ASK_POLL`; `defaults/settings.toml:213`
- Ran: `./bin/sb ask --help` → `usage: sb ask [-h] [--json] [--timeout TIMEOUT] who [who ...] question`

**`wait` — present as a verb**
- `switchboard/cli.py:304-315` `cmd("wait", help="block until an agent reaches a state (for HUMANS,
  not agents)")`; dispatch at `cli.py:911-914`
- `switchboard/status.py:1437` `def wait_for(...)`; `defaults/settings.toml:141, 239, 242`
- The design entry is unconditional ("It has no reason to exist"); the code's justification
  ("for humans, not agents") is a rationale the entry does not grant.

**`interrupt` — present as a verb, not as a delivery mode of `tell`**
- `switchboard/cli.py:288-290` `i = cmd("interrupt", help="change an agent's course mid-flight")`;
  dispatch `cli.py:897-899`
- `switchboard/broker.py:3184` `def interrupt(...)`; its docstring at 3187-3191 argues explicitly
  "**Not a variant of `tell`**", which directly contradicts DESIGN-TRUTH.md:287.
- `./bin/sb tell --help` shows **no** delivery-mode flag of any kind: only `who`, `message`,
  `--json`, and the hidden `--re` (`cli.py:148-151`). So there is no mode for interrupt to be.

**Shipped agent-facing text tells agents to use `ask`**
- `defaults/protocol.md:103-105`: "`sb ask <who> \"<question>\"` sends to another agent and WAITS
  for its answer — for agents only, and only when the answer is seconds away."
- `switchboard/cli.py:3` module docstring: "Seven verbs for agents (`delegate`, `ask`, `tell`, …)"

**`--needs-reply` does not exist**
- `grep -rl "needs.reply"` across the whole repo (excluding `.git`) matches **DESIGN-TRUTH.md only**.
  Nothing in `switchboard/`, `bin/`, `defaults/`, or `tests/`. `./bin/sb tell --help` has no such flag.
- So the replacement mechanism the entry describes is entirely unbuilt: today an agent that needs an
  answer has only the rejected `ask`.

### Gaps (one line each)
1. `sb ask` exists as a blocking verb — remove the subcommand (`cli.py:139-146, 370-373, 739-748`).
2. `Broker.ask` and its poll loop still exist (`broker.py:2713-2789`) along with `ASK_TIMEOUT`/`ASK_POLL` (`broker.py:101-103`, `defaults/settings.toml:213, 226`).
3. `sb wait` exists (`cli.py:304-315, 911-914`) plus `status.wait_for` (`status.py:1437`) and `timeouts.wait*` settings (`defaults/settings.toml:141, 239, 242`).
4. `sb interrupt` exists as its own verb (`cli.py:288-290, 897-899`; `broker.py:3184`) instead of a delivery mode of `tell`.
5. `sb tell` has no delivery-mode flag at all (`cli.py:148-151`) — next-turn/when-idle/interrupt are not selectable.
6. `tell --needs-reply` is unimplemented anywhere in the codebase — the static "you must reply at some point" prompt does not exist.
7. `defaults/protocol.md:103-105` instructs every agent to use `sb ask` and wait — shipped text teaching a rejected verb.
8. `switchboard/cli.py:3-11` and `broker.py:9-25` document `ask`/`wait`/`interrupt` as load-bearing distinctions, so removal means rewriting those headers too.
9. `store.pending_ask` / `reply_to_ask` / `mark_collected` correlation machinery (`broker.py:2687-2708`, `2769`) exists to serve `ask` and needs a decision on removal.
10. ~59 test references to `ask(`/`wait_for(`/`interrupt(` across `tests/` will need rewriting with the verbs.

---

## Entry 2 — "`sb tell` is for agents only, both ways round." (DESIGN-TRUTH.md:229-231)

### Verdict: PARTIAL

**The "cannot address a human" half is SATISFIED, and enforced in code, not just documented.**
- `switchboard/broker.py:2676-2685`: `if t == HUMAN: raise ValueError("the human has no mailbox — a
  message to them would never be read. Use \`sb block …\`")` — raised before any row is written.
- Ran `./bin/sb tell human "audit probe"` →
  `sb: the human has no mailbox — a message to them would never be read. Use \`sb block "<why>"\` …`
  (Nothing written; the guard is before `store.put_message`.) `sb ask human` is refused likewise at
  `broker.py:2739-2745`.
- `defaults/settings.toml:71` records `human` as a non-target for both verbs.
- Agent-facing text is consistent: `defaults/protocol.md` (block is "the ONLY way to reach a human"),
  `defaults/roles/worker.md:52`.

**The "Andrew does not use it" half is BROKEN — the code repeatedly makes `sb tell` the human's verb
for answering a block, and even sends tells as the human.**
- `switchboard/cli.py:161` — the `block` subcommand's own help: *"stop and surface to the human
  (**they answer with `sb tell`**)"*. This is the human being handed `tell`.
- `switchboard/broker.py:2884` — `"The human answers with \`sb tell <agent> \"...\"\`, which rings the
  doorbell …"` in `block`'s documentation of the flow.
- `switchboard/status.py:1084`, `:1140`, `:1316` — the `status`/`--needs-me` surface prints
  `→ sb tell <name> "..."`, `sb tell <name> "wrap up and run sb done"`, `sb tell <name> "answer …"`
  as the suggested human next action.
- `switchboard/cli.py:771` — the human typing `sb inbox` is told: *"answer with `sb tell <agent>
  \"...\"`"*.
- `switchboard/cli.py:715`, `broker.py:3140`, `broker.py:3210` — more human-facing `sb tell …` hints.
- `switchboard/broker.py:562` — `self.tell([name], task, me=HUMAN)`: the broker writes messages whose
  **sender is the human**, so `tell` is not agents-only in the from-direction either. Same shape with
  `me=` a human caller at `broker.py:878, 2094, 2135`.
- There is **no** guard on the sender side: `Broker.tell` checks only the target (`broker.py:2676`),
  never `me == HUMAN`.

DESIGN-TRUTH.md:279-283 also says the human inbox is 100% removed and (203-206) that after a block
"the agent just continues" — but no code path other than `sb tell` is offered for the human to send
that answer, so removing the human's use of `tell` needs a replacement decision, not just a deletion.

### Gaps (one line each)
1. `cli.py:161` block help names `sb tell` as the human's reply verb — contradicts "Andrew does not use it".
2. `status.py:1084, 1140, 1316` print `sb tell …` as the human's suggested action on the board/needs-me surface.
3. `cli.py:715` and `cli.py:771` hint `sb tell` to a human caller.
4. `broker.py:2884, 3140, 3210` document/emit `sb tell` as the human's route.
5. `Broker.tell` has no sender-side human guard (`broker.py:2670-2685`), and `broker.py:562` sends with `me=HUMAN`.
6. No decided replacement exists for how Andrew answers a block if `tell` stops being his — this is a design gap, not just a code one.

---

## Process notes
- Read-only throughout; no code or docs changed, nothing spawned, nothing written inside the repo.
- Two mutating-looking probes (`sb tell human`, `sb ask human`) were run deliberately: both are
  refused before any store write, verified by reading the guards first.
- Both refusals exit **1** with `sb: …` — correct behaviour, no issue.
- No `sb` bug encountered; the CLI behaved as its source says.
# AUDIT 2C — findings: inbox, message prefix, the herdr channel

Auditor: `audit-2c-inbox`. Read-only; no code or docs changed.

**Tree audited:** `/Users/andrew/.herdr/worktrees/switchboard/worker-2` @ `a9dd319`.
**Tree the `sb` on PATH runs:** `/Users/andrew/Code/switchboard` @ `caa6d20` (main), via
`/Users/andrew/.local/bin/sb` → `/Users/andrew/Code/switchboard/bin/sb`, which inserts that
repo root on `sys.path`.
**Do they differ?** No. `git diff --stat caa6d20 HEAD -- switchboard/ bin/ defaults/` is
empty, and the main checkout is clean. So every live run below exercises exactly the code
quoted below, and local `main` fixes none of the gaps.

Verdicts: **0 SATISFIED, 2 PARTIAL, 1 BROKEN.**

---

## Entry 1 — `sb inbox --peek` stays, and once read a message is never brought up again

> "**`sb inbox --peek` stays, and it must be clear that once a message is read it will not
> be brought up again.**" — DESIGN-TRUTH.md:252

### Verdict: PARTIAL

The mechanism is right in every part. The *clarity* half of the entry — "it must be clear"
— is not delivered anywhere an agent will see it.

**`--peek` exists and does not consume** — `switchboard/cli.py:154-156`

```
ib = cmd("inbox", help="read your unread messages")
ib.add_argument("--peek", action="store_true",
                help="do not mark as read (safe for polling)")
```

→ `switchboard/cli.py:774` `msgs = b.inbox(me=me, peek=args.peek)`
→ `switchboard/broker.py:2816-2826` `return store.unread_for(self.db, me or self.whoami(), mark=not peek)`
→ `switchboard/store.py:1271-1286`: rows are selected on `read_at IS NULL`, and `read_at`
is only written `if rows and mark`. So `--peek` leaves `read_at` NULL. Confirmed live:
`sb inbox --help` prints both flags; `sb inbox --peek` and `sb inbox --peek --json` returned
`(no new messages)` / `{"messages": []}`.

**A normal `sb inbox` marks read, and read messages are never re-shown or re-delivered**

- Re-shown: `store.unread_for` (store.py:1278) filters `read_at IS NULL`, so a read row can
  never come back out of `sb inbox`.
- Re-delivered: the doorbell sweep is `Broker.flush_pending` (broker.py:3337), which reads
  `store.unseen(...)` — and `unseen` (store.py:1311-1326 → `_pending`, store.py:1329-1341) is
  `delivered_at IS NULL AND read_at IS NULL`. A read row is excluded forever. store.py:1314-1324
  documents this as the exact reason `unseen` exists rather than `undelivered`.
- Verified live against the store (`/Users/andrew/Code/switchboard/.git/agentflow/state.db`):
  my own message row is `{'id': 357, 'to_agent': 'audit-2c-inbox', 'read_at': 1786317955,
  'delivered_at': 1786317949}` after one `sb inbox`, and a subsequent `sb inbox --peek`
  returned nothing.

**Where it falls short — nothing tells the agent this.** The protocol prompt every agent
gets says only (`defaults/protocol.md:99`):

```
`sb inbox` reads your unread messages — run it whenever you are told you have mail.
```

That is the entire treatment. It does not say reading consumes, it does not say a read
message will never be raised again, and it never mentions `--peek` at all — so the flag the
entry protects is invisible to the only population that can use it. The `sb inbox` output
itself (cli.py:778, `[{id}] from {sender}: {body}`) adds no such note either.

### Gaps (entry 1)

- `defaults/protocol.md:99` does not state that `sb inbox` consumes: a read message is never
  shown or announced again.
- `defaults/protocol.md` never mentions `sb inbox --peek`, so no agent knows a non-consuming
  read exists.
- `sb inbox`'s own output (`switchboard/cli.py:778-780`) prints messages with no line saying
  they are now read and will not reappear.
- `--peek`'s help text says "do not mark as read (safe for polling)" but not the converse —
  that a plain `sb inbox` is one-shot (`switchboard/cli.py:155-156`).
- Side effect worth a task: a peeked message that was already rung has `delivered_at` set and
  `read_at` NULL, so `unseen` will never ring for it again (store.py:1336-1337) while
  `cleanup`'s unread gate still counts it — a peek-only agent can pin itself open.

---

## Entry 2 — every sb message is prefixed so it is clearly an sb message

> "**Every sb message is prefixed so it is clearly an sb message**, and the prefix can carry
> more — the sender agent's name and the like. The channel is the same as Andrew typing; the
> prefix is what tells them apart." — DESIGN-TRUTH.md:90-92

### Verdict: BROKEN

Nothing sb puts on the wire into a Claude chat box carries an sb marker or a sender name.
The prefixing that does exist is in the wrong place: inside `sb inbox`'s *tool output*, which
is not the channel the entry is about.

**The wire has no prefix.** Every message into the chat box goes through `Broker._ring`
(broker.py:3386) → `self.h.prompt(who, text)` (broker.py:3431) → `herdr.py:471`
`self._call("agent", "prompt", name, text)`. `text` is passed through untouched at all three
levels — there is no prefixing step anywhere on the path.

The four texts that travel it, from `defaults/prompts.toml`:

| line | text as sent |
|---|---|
| `prompts.toml:63` | `mail = "You have mail. Run: sb inbox"` |
| `prompts.toml:71` | `mail_question = "You have mail (a question) — someone is waiting…"` |
| `prompts.toml:81` | `child_done = "A child finished. Run: sb inbox. …"` |
| `prompts.toml:93` | `interrupt = "[INTERRUPT — stop now] …"` |

Only `interrupt` carries a bracketed prefix, and it announces *urgency*, not sb-origin and
not a sender. The other three are bare sentences indistinguishable from something Andrew
typed.

**Spawn task delivery is the same** — `switchboard/broker.py:2646` `self.h.prompt(name, task)`
sends a child's first task raw, unprefixed and unattributed.

**Live proof, from this very session.** My first turn arrived as the task line and the
doorbell concatenated with no separator and no marker:

```
Read /tmp/sb-audit-2c-inbox.md and carry out exactly what it says.You have mail. Run: sb inbox
```

Nothing there says "sb", nothing says who sent it.

**What prefixing does exist, and why it does not count.** `switchboard/cli.py:778` renders
inbox rows as `[{id}] from {from_agent}: {body}` — which is how I saw
`[357] from audit-2b: …`. That is a *tool result* inside a turn the agent already chose to
spend, not the channel Andrew shares. Likewise `vocabulary.done_prefix = "[done] "`
(`defaults/settings.toml`, used at `switchboard/status.py:183,690-691`) is explicitly an
internal marker that readers **strip** — settings.toml calls it "an implementation detail of
the mailbox rather than something everyone must know". Neither satisfies the entry.

### Gaps (entry 2)

- `Broker._ring` (`switchboard/broker.py:3386-3438`) applies no prefix before
  `self.h.prompt(who, text)` — add one central prefixing point there so nothing can bypass it.
- `defaults/prompts.toml:63,71,81` (`notify.mail`, `notify.mail_question`, `notify.child_done`)
  carry no sb marker; they read exactly like a human-typed line.
- No sender name reaches the chat box on any path — the entry's "the prefix can carry more —
  the sender agent's name" has no implementation at all.
- `switchboard/broker.py:2646` delivers a spawned child's first task unprefixed and
  unattributed, so an agent cannot tell its task from a human's typing either.
- `notify.interrupt`'s `[INTERRUPT — stop now]` (`defaults/prompts.toml:93`) is the only
  bracketed marker and it is not an sb marker — if a scheme is chosen it should subsume this
  rather than sit beside it.

---

## Entry 3 — how herdr actually talks to Claude

> "**How herdr actually talks to Claude.** It types into the chat box and presses enter… If
> Andrew is halfway through typing when a message is sent, the half-written text goes along
> with it, because sb pastes and hits enter. While Claude is working, a message is queued by
> Claude's own system and delivered on the next turn. Interrupt is pressing escape on the
> chat window, which interrupts the model, and then the message goes in directly without
> waiting." — DESIGN-TRUTH.md:82-88

### Verdict: PARTIAL — the interrupt half is exactly right; the queueing half is contradicted
by the code, and the paste-and-enter half is not sb's code to evidence.

**(a) Types into the chat box / paste-and-enter — UNVERIFIED at source, corroborated live.**
sb never types anything itself on this path: it shells out to `herdr agent prompt <name>
<text>` (`switchboard/herdr.py:471`), and the typing happens inside the herdr binary, which
is not in this repo. `herdr agent prompt --help` documents it only as "Submit a prompt to an
agent". The nearest in-repo corroboration is the *pane* path, `Herdr.prompt_pane`
(`herdr.py:473-489`), whose comment records the measured behaviour — "`pane run` types but
does not reliably submit into a TUI prompt box, so the explicit `enter` is required" — and
which does `pane run` then `pane send-keys <pane> enter`. The half-typed-text claim is
directly corroborated by this session: audit-2b reported my task "was left sitting unsent in
your prompt box", and it arrived fused to the doorbell with no separator (quoted under entry
2). That is paste-and-enter behaviour observed, not proven from source.

**(b) "While Claude is working, a message is queued… delivered on the next turn" —
CONTRADICTED by the code, in comments *and* in design.** `Herdr.prompt`
(`switchboard/herdr.py:457-470`):

```
**This INTERLEAVES. It does not queue.** An earlier note here said the opposite… Re-verified
against a genuine 60-second multi-step turn: the poke was handled at +13s while the running
task did not complete until +63s.
```

The same claim is load-bearing in the broker, not incidental: `broker.py:11-15` ("a prompt
INTERLEAVES rather than queues"), `Broker._ring` (`broker.py:3389-3392`), and the actual
guard `if not force and self._busy(who): … return False` (`broker.py:3426-3428`) which
*defers every doorbell while the target is mid-turn*. `store.undelivered`
(`store.py:1292-1295`) repeats it. So the whole deferral machine exists **because** the code
believes the opposite of this sentence. One of the two is wrong; per this repo's rules
DESIGN-TRUTH wins and the code contradicts it, which is a decision for Andrew, not for me.

**(c) Interrupt is escape, then the message goes in directly — SATISFIED.**
`Broker.interrupt` (`switchboard/broker.py:3184-3226`):

```
3216:  self.h.send_keys(name, "esc")
3217:  time.sleep(INTERRUPT_SETTLE)   # let the cancel land before the new one
3220:  body = self._say("notify.interrupt", text=text)
3224:  self._ring(name, body, force=True)
```

`send_keys` → `herdr agent send-keys <name> esc` (`herdr.py:491-499`); `herdr agent send-keys
--help` confirms "Use esc as the canonical Escape key name". `force=True` is what bypasses
the busy-defer in `_ring` (`broker.py:3426`), so the text does go in directly without
waiting, and the payload travels **inline** here rather than as a bare doorbell — matching
"the message goes in directly".

### Gaps (entry 3)

- `switchboard/herdr.py:460-468` asserts `agent prompt` INTERLEAVES and does not queue,
  directly contradicting DESIGN-TRUTH.md:85-86 — needs Andrew to say which is true before
  anything is built on either.
- The entire busy-defer path (`Broker._ring`, `switchboard/broker.py:3426-3428`, plus
  `flush_pending` at 3348-3351) is built on the interleaves belief; if the truth entry stands,
  deferring while working is unnecessary machinery and messages are being delayed for nothing.
- `store.undelivered` / `unseen` docstrings (`switchboard/store.py:1292-1295, 1311-1324`)
  restate the interleaves claim, so a correction has three files to land in, not one.
- The paste-and-enter mechanism is unevidenced in this repo — it lives in the herdr binary.
  If it matters it should be pinned by a test or a recorded observation, not left to a
  comment on a different code path (`herdr.py:485-489`).

### Adjacent, out of my scope — reported, not fixed

- `sb interrupt` is a top-level verb (`sb --help`, `switchboard/cli.py`), while
  DESIGN-TRUTH.md:287 rules out "`sb interrupt` as a verb" and DESIGN-TRUTH.md:216-227 makes
  interrupt a delivery *mode* of `tell`. `sb tell` currently has no mode flags at all
  (`switchboard/cli.py:148-151`). Belongs to whoever owns the delivery-modes entry.
- `sb ask` still exists (`sb --help`, `broker.py:2713`) against DESIGN-TRUTH.md:283.

---

## Process notes

- My task was not delivered on spawn — it sat unsent in my prompt box and only went in when
  audit-2b's follow-up message pushed it through. That mis-delivery is itself evidence for
  entries 2 and 3 and is quoted above.
- Nothing was committed: the task is read-only and the report lives at
  `/tmp/sb-audit-2c-inbox.md`, outside the repo, as instructed.
- No agents were spawned; every check was a non-mutating read (`sb --help`, `sb inbox --help`,
  `sb inbox --peek`, `herdr … --help`, a read-only SQLite query).
