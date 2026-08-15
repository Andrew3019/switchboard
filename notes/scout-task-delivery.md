# Scout report — task delivery bug

Checked against HEAD in this worktree (branch `task-delivery-fix`). Everything below is by
reading; no code changed, nothing run against a live herdr.

## A. The delivery path, end to end

**`switchboard/herdr.py`**

- `Herdr.prompt(name, text) -> None` (line 600) — the raw `agent prompt <name> <text>` call.
  Fire-and-forget: return value proves nothing (docstring is explicit about this).
- `Herdr.deliver(name, text, *, attempts=DELIVER_ATTEMPTS, timeout_ms=DELIVER_TIMEOUT_MS, working_ms=DELIVER_WORKING_MS, proof=None) -> None` (line 628). Loop, up to
  `attempts` times: snapshot `before = self._peek(name)`, record `sent = time.time()`, call
  `self.prompt(name, text)`, then `self._took_prompt(name, before, timeout_ms, sent=sent,
  proof=proof, working_ms=working_ms)`. First truthy return → success, done. Otherwise sleeps
  `SPAWN_BACKOFF` and tries again (baseline re-peeked every time — deliberately, see the
  docstring at line 675). Exhausts all `attempts` → raises `HerdrError("not_delivered", ...)`.
  **On retry it does exactly one thing differently from the first send: nothing.** The retry
  is `self.prompt(name, text)` again, verbatim — no `send_keys`, no clearing of the prompt
  box, no explicit `enter`. The docstring (lines 679–685) *claims* "the second prompt types
  and presses enter, carrying the stuck text in with it" — **that sentence is not true of the
  code.** Flagging this per your instruction: the bug report's assertion that "nothing in
  HEAD clears the box or sends an explicit enter" is correct; the docstring it's describing
  is aspirational, not descriptive.
- `Herdr._took_prompt(name, before, timeout_ms, *, sent, proof=None, working_ms=DELIVER_WORKING_MS) -> bool` (line 726). Polls twice a second
  (`DELIVER_POLL` = `timeouts.deliver_poll` = 0.5s) until `timeout_ms` elapses. Each poll:
  if `proof` given, call `proof(sent)` — return True the moment it does. Otherwise fall back
  to `self._running_turn(name, seq, was_working)`. **If the window runs out and herdr reports
  `working`, the deadline is stretched ONCE by `working_ms`** (this is the fix for the "proof
  flushes late" problem — already in HEAD, well tested, see D below). If `proof` is None, no
  stretch and this just returns the status read's answer.
- `Herdr._running_turn(name, seq, was_working) -> bool` (line 773). `state == WORKING and
  (change_seq > seq or not was_working)` — a *turn starting*, not just any status move (this
  is the fix for the "workspace-trust dialog eats the prompt and flips state anyway" bug —
  also already in HEAD).
- `Herdr.send_keys(name, *keys) -> None` (line 825). Thin wrapper on `agent send-keys`.
  **Confirmed: its only caller anywhere in the tree is the interrupt path**,
  `broker.py:4015` (`self.h.send_keys(name, "esc")`, to cancel a turn before an interrupt
  lands). Nothing in the delivery path calls it. This matches the bug report exactly.

**`switchboard/output.py`**

- `task_arrived(cwd: Optional[str], text: str, *, since: float) -> bool` (line 138). **It
  already takes `since` — nothing needs adding there.** Finds `store.transcript_dir(cwd)`,
  skips any `.jsonl` untouched since `since - _CLOCK_SLOP` (5.0s), reads only the tail
  (`_ARRIVAL_RECORDS` = 50 records) of the rest, and returns True the first time it finds a
  `type: "user"` record (not older than the floor) whose content contains `text.strip()`
  verbatim. Matches by content, not session id, because an agent that never took the prompt
  never started a session at all.

**`switchboard/broker.py`**

- `Broker._spawn`'s delivery block (lines 3244–3286, inside the larger `_spawn`/`delegate`
  method). After `start_agent` + `mark_spawned` + `_open_board`, it calls:
  ```
  self.h.deliver(name, task,
                 proof=lambda since: output.task_arrived(str(where), task, since=since))
  ```
  (`where` is the `Path` the agent's cwd was resolved to a few lines earlier, ~3114–3118 —
  a worktree path, a recorded workspace path, or `self.repo`.) `deliver` uses its default
  `attempts=DELIVER_ATTEMPTS`, `timeout_ms=DELIVER_TIMEOUT_MS`, `working_ms=DELIVER_WORKING_MS`
  — none overridden here. On success, `return name`. On `HerdrError`, the except block
  (3249–3285) calls `alive = self._took_a_turn(name)`; if truthy, logs `task_unconfirmed`,
  sets `self.delivery_note`, and **still returns `name`** (soft failure — the false-negative
  fix already covers the "state changed to working before the read" case, just not the
  transcript). If `alive` is falsy: `store.set_state(self.db, name, GONE_STATE)`, logs
  `task_undelivered`, raises `TaskUndelivered(name, e)`.
- `Broker._took_a_turn(name) -> Optional[str]` (lines 3288–3318). **This is the safety net
  the report names, and the report's description of it is accurate at HEAD.** It checks,
  in order: (1) the store row — if `state in ("done", "blocked")`, return a reason string
  (written by the agent itself, trusted); (2) one direct `self.h.get_agent(name)` probe — if
  `state == WORKING`, return a reason string. Otherwise `None`. **It never calls
  `output.task_arrived`.** So an agent whose transcript already holds the proof, but whose
  herdr status hasn't caught up (the exact 0.9s-late case in the incident) and whose store
  row isn't yet `done`/`blocked`, gets `alive = None` → `GONE_STATE` → `TaskUndelivered`
  raised. This confirms the report's diagnosis of half (1) precisely, down to the line
  number it cites (broker.py:3287, one off from the def line 3288 — the report is citing the
  call site inside the except block, not the def; both point at the same function).

**Timings/retries, and where they come from** (`defaults/settings.toml`):
- `timeouts.deliver_ms = 20000` → `DELIVER_TIMEOUT_MS`, herdr.py:60.
- `timeouts.deliver_poll = 0.5` → `DELIVER_POLL`, herdr.py:61.
- `timeouts.deliver_working_ms = 60000` → `DELIVER_WORKING_MS`, herdr.py:65 (the one-time
  stretch when herdr says `working` but no proof yet — already the fix for "proof flushes
  late", not the bug this task is about).
- `retries.deliver_attempts = 3` → `DELIVER_ATTEMPTS`, herdr.py:62.
- `retries.spawn_backoff = 2` → `SPAWN_BACKOFF`, herdr.py:55 (linear backoff between deliver
  attempts too, not just spawn attempts — `deliver`'s loop reuses it, herdr.py:700).

The incident's "84s = 3×20s deliver_ms + backoffs, no working_ms stretch" lines up exactly
with this: 3 attempts × 20s + 2×backoff(2,4)... the report's own arithmetic, not rechecked
digit-for-digit here, but the mechanism (no stretch because herdr never reported `working` in
time) is consistent with `_took_prompt`'s stretch condition at herdr.py:766–771, which only
stretches when `self._running_turn(...)` is true at the moment the window expires.

## B. Smallest honest change per half

**Half 1 — false negative (`_took_a_turn` doesn't consult the transcript).**

Confirmed true at HEAD, exactly as the report states. Smallest change: give
`Broker._spawn` the timestamp of its first send, and have the except-path consult
`output.task_arrived` with it before falling back to `_took_a_turn`'s weaker signals — or
add it as a third check inside `_took_a_turn` itself. Concretely, touches only
`switchboard/broker.py`:
- Capture `since = time.time()` immediately before the `self.h.deliver(...)` call
  (~line 3244) — this is already almost exactly `sent` from inside `deliver`'s first
  attempt, close enough for `task_arrived`'s 5s clock-slop floor.
- In the except block (or inside `_took_a_turn`, which would need `task` and `where` passed
  in, currently takes only `name`), call `output.task_arrived(str(where), task, since=since)`
  as one more check, ideally first (it's the strongest evidence — the same thing `deliver`'s
  own `proof` trusts) or alongside the two existing checks.
- No change needed in `output.py` (the `since` param already exists) or `herdr.py`.

**Half 2 — retry duplication, no rescue.**

Confirmed true at HEAD; the docstring claim is false. Smallest change lives entirely in
`Herdr.deliver`'s retry body (herdr.py, inside the `for attempt in range(attempts)` loop,
lines ~688–700). Instead of unconditionally calling `self.prompt(name, text)` on every
attempt including retries, a retry (attempt > 0) should first try to *rescue* a stuck box
rather than blindly pasting again — e.g. send an explicit `enter` via `self.send_keys(name,
"enter")` to submit whatever is already sitting there, give `_took_prompt` a short chance to
confirm that, and only fall through to another `self.prompt(name, text)` if that didn't work
(box was genuinely empty, e.g. herdr lost the pane entirely). This is a decision I'm
deliberately not making for you (you said don't write the code) — the two live options are
"rescue-then-resend" (send enter, check, then resend if still nothing) vs "clear-then-resend"
(some way to blank the box first, if one exists — I did not find a documented "select all /
clear" key in this codebase, only `esc` and `enter` are attested as key names anywhere in the
tree). Whoever implements this needs to find out from herdr's own docs/CLI help what key
names `agent send-keys` accepts beyond `esc`/`enter`, since nothing in this repo names a third
one.

## C. Do the two halves overlap?

**No function or line overlap.** Half 1 touches only `switchboard/broker.py` (the except
block of `_spawn`'s delivery try, and/or `_took_a_turn`'s signature and body). Half 2 touches
only `switchboard/herdr.py` (`Herdr.deliver`'s retry body). Neither half's smallest-honest
version needs to change `output.py`, `Herdr._took_prompt`, or `Herdr._running_turn`. They can
be written and reviewed by two people in parallel with no merge risk between them — the only
shared surface is that both are reachable from the same `delegate()` call, not that they edit
the same code.

## D. How this could be proven live

Read `sb presets house-rules` — done. Two or three tests, no growing the fake, isolate with a
`git clone`, no endurance testing, tear down everything.

**Existing coverage today (both already well tested — worth knowing so a fix doesn't
duplicate what's already pinned):**
- `tests/test_herdr.py::DeliverTest` and `DeliverProofTest` (from ~line 243) — cover
  `Herdr.deliver`/`_took_prompt` thoroughly at the argv-fake level: re-send on no-turn,
  raise after exhausting attempts, baseline re-read every send, proof-only confirmation,
  the `working_ms` stretch and its "exactly one moment too late" edge (`late()` helper,
  ~line 427). None of these exercise the *retry's own mechanics* (what it sends on a
  retry) beyond "does `self.prompt` get called again" — they don't assert anything about
  `send_keys`, because today nothing calls it.
- `tests/test_broker.py` (~lines 287–361) — covers the broker-level safety net exactly as
  it exists today: `task_that_never_arrives_fails_the_spawn_loudly`,
  `an_unconfirmed_delivery_to_a_working_agent_is_not_a_failed_spawn` (the `_took_a_turn`
  "herdr says working" branch), `an_agent_that_reported_done_is_never_recorded_failed` (the
  "store row says done/blocked" branch). **No test here exercises the transcript branch,
  because there isn't one yet** — that's the gap half 1 fills.
- `tests/test_output.py::TaskArrivedTest` (~line 250) covers `task_arrived` itself
  thoroughly, including the exact "since" semantics half 1's fix would rely on, using a
  `write_transcript` helper against a faked `HOME`.

**Smallest new automated test per half (2–3 total, pinning the decision, not for
confidence):**
- Half 1: one test in `tests/test_broker.py`, same shape as the existing three delivery
  tests — `FakeHerdrAPI` reports the agent NOT working and the store row NOT done/blocked
  (so today's `_took_a_turn` returns `None`), but a real transcript file is written to a
  real temp dir (reusing the `write_transcript`/fake-`HOME` pattern already established in
  `test_output.py`, not growing `FakeHerdrAPI` — this is writing an actual file, not
  teaching the fake a new trick) containing the task text, timestamped after `since`.
  Assert `delegate()` does **not** raise `TaskUndelivered`, and the row is not stamped
  `GONE_STATE`. This is a real gap: it cannot pass today, because `_took_a_turn` never
  looks at the filesystem.
- Half 2: one test in `tests/test_herdr.py`, same shape as `DeliverTest.herdr()`'s
  `takes_on=2` case (which already models "doesn't take it on send 1, takes it on send 2" —
  i.e. already models paste-without-submit at the *outcome* level). Add an assertion on the
  **call sequence**, not a new fake capability: with the fix, the calls between send 1 and
  the eventual success should include an `["agent", "send-keys", "w1", "enter"]`-shaped call
  (or whatever key name is chosen) before the second `["agent", "prompt", ...]`. The
  existing fake already records raw argv for any call including `send-keys` (it falls into
  the same "not agent prompt" branch and answers with a status read, which `send_keys`
  doesn't parse) — so this doesn't require growing it.

**What the existing fake genuinely cannot express, per your instruction not to grow it:**
The fake herdr, at both layers (`test_herdr.py`'s argv-replay `FakeHerdr` and
`test_broker.py`'s `FakeHerdrAPI`), has no model of *pane/box content* — only of agent
*state* (idle/working/done/blocked) and of a list of calls made. "Two `agent prompt` calls
either both land as one message or neither lands" is a fact about what a real terminal does
with two pastes into one box; nothing here simulates a box or partial input. So the tests
above can prove "the fix sends a rescue key instead of blindly re-pasting" (a change in
*behavior*, argv-level) but **cannot** prove "and that rescue key actually prevents a
double-submit in a real pane" — that half is only provable live. Don't grow the fake to
cover it; say so instead.

**Smallest live proof, in an isolated clone:**
- Setup once: `git clone` this repo into a scratch dir, check out this branch there, drive
  that clone's own `./bin/sb` only, per house rules. Tear down every agent/pane spawned.
- **Half 1** — force the exact race: lower `timeouts.deliver_ms` and
  `timeouts.deliver_working_ms` to near-zero for one clone-local run (a settings override,
  not touching `defaults/settings.toml`) so `deliver`'s own stretch can't rescue a
  genuinely-working agent, exhausting all 3 attempts before herdr ever reports `working`.
  Spawn one agent with `sb delegate`. Before the fix: expect `sb delegate` to exit 1 and
  `sb status <name>` to show the row `failed`/gone even though the agent is genuinely
  running (visible in `sb inspect <name>` / its own transcript). After the fix: expect `sb
  delegate` to still exit 0 (or return the name with a note) and the row to stay `working`,
  because the transcript check now catches what the timing race missed. This is the
  smallest run that can tell fixed from broken for half 1 — one spawn, deliberately starved
  timings, no fan-out needed.
- **Half 2** — the report notes "on a cold checkout the first send is lost far more often
  than not," i.e. a *fresh* clone's first spawn is the highest-probability repro, no
  artificial starving needed. Spawn one agent in a freshly created clone/worktree (cold, no
  warm herdr/Claude-Code state) via `sb delegate` and read its resulting transcript
  (`sb inspect <name>` or the transcript file directly) for how many times the task text
  appears. Before the fix: sometimes duplicated (both copies submitted as one message),
  sometimes absent (agent starts with an empty session or none at all). After the fix:
  exactly once, every time you can get the race to reproduce. Because this is only
  probabilistically reproducible, house rules' "rare and slow-burn faults are accepted, they
  surface in real use" applies — a handful of cold-clone spawn attempts is a reasonable
  smallest run, not a loop hunting for the race.

## Summary of what the report gets right vs. wrong about the code at HEAD

- Half 1 diagnosis (broker.py `_took_a_turn` never reads the transcript): **accurate**,
  confirmed line-for-line.
- Half 2 diagnosis (`send_keys`'s only caller is the interrupt path, delivery never uses
  it): **accurate**, confirmed — `broker.py:4015` is the only call site in the tree.
- One thing the report doesn't call out but is worth flagging: `deliver`'s own docstring
  (herdr.py:679–685) already **claims** the retry "types and presses enter, carrying the
  stuck text in with it." That's not a stale claim about old code being fixed — it's a
  docstring describing behavior the code has never had. Whoever writes half 2 should
  correct the docstring alongside the fix, since right now it actively misdescribes what
  `deliver` does.
- `output.task_arrived` already taking a `since` argument (the report leaves this an open
  question — "would that need adding?") — **it does not need adding**, it's there today.
