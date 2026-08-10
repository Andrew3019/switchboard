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
