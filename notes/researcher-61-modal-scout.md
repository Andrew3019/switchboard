# Scout: STALLED path and feasibility of a generic modal detector

Scout only, task `.scout/modal-scout.md`. Nothing changed. All line refs against this
worktree's HEAD of the named files. Overlaps with, and confirms,
`notes/researcher-45-stalled-agent-lifecycle.md` on the state model — that note is the
deeper map of `agents.state`/`agents.turn`; this one is scoped to the modal question.

## 1. Where STALLED is computed

- `switchboard/status.py:AgentStatus.stalled` — not a `@property`, a field computed once
  per `collect()` call and stamped on the row (status.py:333 decl, computed
  status.py:912/933: `idle = bool(running and turn_over and alive is not False)`,
  `stalled = idle and excuse is None`).
- `turn_over` (status.py:899-900) prefers switchboard's own `agents.turn` column
  (`turn == TURN_IDLE`) and only falls back to herdr's `agent list` state
  (`hstate in IDLE_LIKE`) when `turn is None`. `agents.turn` is written only by the two
  hooks in `hooks.py` (`UserPromptSubmit`→`working`, `Stop`→`idle`).
- `excuse` (status.py:908-911) is the whitelist of reasons idle is not a stall:
  `awaiting_task`, a live child (`live_parent`), or still starting (`starting`,
  session-id grace). If none apply and the agent is idle, `stalled=True`.
- Drawn: `board.py:marker()` (board.py:203-220) turns `a.stalled` into the literal string
  `"STALLED — idle {age}"` shown in the row; `board.py:wants_you()` (190-200) is what puts
  it in the NEEDS YOU membership test, alongside `gone`, `signal_drift`, `blocked`,
  `at_prompt`. `richboard.py` (NEEDS YOU section, ~line 279 for membership order,
  `marker_short` at 126) draws the same predicate for the rich TUI board.
- Sibling states on the same row, all mutually distinguished in `AgentStatus`
  (status.py:335-660): `gone` (herdr no longer lists the pane, confirmed over a debounce —
  `_confirmed_gone`/`_record_gone`), `signal_drift` (our signal says working, herdr sees
  no recognisable agent at all — `herdr_state == UNKNOWN`), `turn_doubted` (our signal says
  working, herdr says idle — the *repair* path, not shown directly, it just clears the
  stuck `turn` edge so `stalled` can fire honestly), `blocked` (the store's own `state`
  column, set by `sb block`), `at_prompt` (`herdr_state == BLOCKED`, herdr's own detector
  for "a permission prompt or similar is sitting unanswered on screen" — status.py:534-542).

None of `gone`, `stalled`, `signal_drift`, `turn_doubted` or `at_prompt` reads pane text.
Every one of them is built from `agents.turn` (our own hook signal) and `herdr_state`
(herdr's coarse four-value enum: `idle | working | blocked | unknown`) plus timers. **A
modal is not a value any of these can already see** — see §2/§3.

## 2. What raw pane signal exists, and its cost

- `Herdr.read_pane(pane_id, lines=...)` (herdr.py:901-937) runs `herdr pane read <id>
  --source recent --lines N` as its own subprocess, one call per invocation, and returns
  the pane's visible text (raises on a closed pane; caller falls back to the transcript).
- Today this is called from exactly one place: `output.read_output`
  (`switchboard/output.py:92-136`, the `sb inspect` pane view), on demand, one agent at a
  time, never on a timer.
- The periodic refresh loop (`switchboard/collector.py`, ticks every
  `display.board_refresh` seconds) calls `Herdr.list_agents()` — one `herdr agent list`
  subprocess for the *whole fleet* — and nothing else herdr-side. `status.collect()`
  (status.py:701-986), which the collector calls every tick, never calls `read_pane`.
- Cost of adding it: `read_pane` is one subprocess spawn per agent (herdr.py:911-914 uses
  `self._spawn`, the same primitive as every other herdr call, bounded by
  `SUBPROCESS_TIMEOUT`). `list_agents()` is O(1) subprocess for N agents; `read_pane` for
  a modal check would be O(N) subprocesses per tick — collector.py's own docstring
  measures a single `git rev-parse` at 12.3ms of a 23.4ms tick, "more than the herdr call
  and all of the SQL together," so N extra subprocess spawns every `board_refresh` seconds
  is a real, multiplying cost, not a rounding error, and scales with fleet size.
- No caching or incremental read exists — every `read_pane` call re-reads the last N lines
  fresh.

## 3. Is a GENERIC modal detector feasible

Short answer: **I could not confirm one, and the direct evidence available says herdr's
own detector — which already screen-scrapes the pane for state — misses at least one real
modal outright.** I did not find a structural marker (box-drawing, cursor position, absence
of the input box) documented or captured anywhere in this repo; nothing here rasterizes or
snapshots real Claude Code modal screens for pattern study.

What is on record instead, from `notes/stuck-agent-interrupt.md` (a prior live
investigation, not code I wrote):
- A real Claude Code first-run dialog (the login-method picker) was sitting on screen
  while `herdr agent get <name>` reported `"interactive_ready": true, "agent_status":
  "idle"` — i.e. herdr's own state classifier, which *does* watch the pane (spinner
  glyphs, terminal title per `status.py`'s module docstring), read a modal as ordinary
  idle. That is direct evidence against "the modal has an obvious structural signature
  herdr's classifier would already have caught."
- The dialog in question had no Escape binding at all for that screen — "some early
  screens simply don't listen for it" — so even interaction behaviour is not uniform
  across modals, let alone visual structure.
- `notes/auto-mode-dialog-suppression.md` documents one *specific* dialog's gate
  (`skillOverrides["auto-mode-setup"]`) reverse-engineered from the decompiled `claude`
  binary, and suppresses it by never letting it render — it says nothing about what the
  dialog looks like on screen or how to recognise it after the fact, because the fix
  avoids needing to.
- Claude Code modals are visually heterogeneous by design intent (trust-folder prompt,
  login/auth screens, theme picker, permission prompts, auto-mode setup) and at least
  the two documented here already differ in interactivity (Escape works on one, not the
  other), which is a bad sign for a single structural rule covering all of them.

I looked for captured pane fixtures or screenshots of these screens under `tests/` and
found none — `tests/test_panel.py` is the only pane/fixture-adjacent file and it is about
the board's own rendering, not Claude Code's. So there is no example corpus in-repo to
derive a generic pattern from; the honest position is that feasibility is currently
**unproven in either direction on visual structure**, and the one piece of direct
evidence available (herdr misreading a real modal as idle) argues against "obviously
detectable," not for it. I would not build a generic detector on box-drawing/prompt-line
heuristics without first capturing several real modal screens and checking a rule against
all of them — that capture work is itself the open question, not something this scout did.

One structural signal *is* plausible in principle and worth naming even though I could
not verify it here: `herdr_state == UNKNOWN` (the reading `signal_drift` already keys
off, status.py:456-462) is herdr's classifier returning "no rule matched" — Claude Code
running, but not in any state herdr's own screen-scraper recognises. A modal is one thing
that could produce that reading, but so could plenty of other things (a paused shell, a
foreign TUI, herdr's own weak spots — the module docstring already names the working→idle
break as one instance of the same classifier being fragile), so `UNKNOWN` is a *candidate
trigger to read the pane on*, not a detector by itself. That would still need `read_pane`
text to disambiguate — see §2 for its cost if run per-tick instead of only when `UNKNOWN`
narrows the candidate set first.

## 4. How honest STALLED is told apart from a modal wedge today, and what would have to hold for a detector not to regress it

Today: **it isn't told apart at all.** A pane parked on a modal that herdr's classifier
happens to read as idle-ish is architecturally indistinguishable from a genuinely finished
turn that never called `sb done`: both end up `turn_over=True` (via the herdr fallback, if
the hook never fires, or even via the hook if `Stop` somehow fired first — see §1) and
`stalled=True` if no excuse applies. Both draw the identical `"STALLED — idle Nm"`.

The honest-STALLED case is currently identified only structurally, not semantically — a
row with `state in RUNNING`, no live children, no awaited-first-task, past the startup
grace, and `turn_over` true. Nothing distinguishes *why* the turn looks over.

For a modal detector to not regress this, it would have to:
- Only ever *add* a new, narrower label (e.g. "waiting on keypress") layered **on top of**
  the existing STALLED/NEEDS-YOU predicate, never replace or suppress it — because a false
  negative on the detector (modal misread as no-modal) must fall back to exactly today's
  STALLED, not disappear from NEEDS YOU. `board.marker`'s existing strict-rank pattern
  (gone > at_prompt > blocked > stalled > signal_drift, board.py:203-220) is the place such
  a label would slot in, ranked wherever it's judged most actionable.
- Be conservative on false positives too: misreading a genuinely-finished, no-`sb-done`
  turn as "parked on a modal" would send a human toward pressing a key that does nothing,
  which is a worse UX than today's honest (if unhelpful) "STALLED".
- Cost nothing when it doesn't fire — collector.py's docstring is explicit that idle costs
  nothing is a designed principle (`notes/PRINCIPLES.md` C10, cited at herdr.py:566-573
  for the same reason mail-ringing avoids polling). A detector that reads every pane every
  tick violates that unless it's gated behind a cheap pre-filter (candidate: `herdr_state
  == UNKNOWN`, see §3), and even then only recompute among the already-stalled candidate
  set, not the whole fleet.

## 5. Where status tests live, and what the fake herdr can/can't express

- `tests/test_status.py` — the join tests (`FakeHerdr`, test_status.py:30-42) implement
  only `list_agents()` returning canned `Agent` objects (`state`, `session_id`,
  `terminal_id`, `pane_id`). No `read_pane`, no pane text, no box content at all.
- `tests/test_herdr.py`, `tests/test_inspect.py`, `tests/test_broker.py`,
  `tests/test_workspace.py` each define their own local `FakeHerdr`/`FakeHerdrAPI` — same
  shape, list/agent-level fakes, not pane-content fakes.
- `notes/fix-half2-herdr.md` (§"What is not proven") says this explicitly, independent of
  my read: **"Neither fake herdr models pane or box content."** — the automated suite can
  prove call sequences (e.g. "a retry sends `enter` before a second `agent prompt`") but
  cannot prove anything about what a real terminal's screen shows.
- Consequence for a modal detector: any behaviour keyed on pane *content* (not just herdr's
  four-value state enum) is untestable by the existing fake herdr as-is, and the brief says
  not to grow the fake. That means a modal detector's core logic — the part that decides
  "this text looks like a modal" — would have to be a pure function of a text string,
  unit-tested directly on captured/hand-written string fixtures (no fake herdr involved),
  with only its *wiring* into `collect()`/`read_pane` left unverified by the automated
  suite, the same "automated proves the mechanism, live proves the behaviour" split
  `fix-half2-herdr.md` already used for the rescue-key fix.

## Also — issue 38

`gh issue view 38 --comments`: the auto-mode-dialog half of #38 is **closed** (#60,
merged `f739a9b`), by suppressing that one specific dialog via a repo-scoped
`skillOverrides` setting so it never renders — not by detecting it. The comment thread
explicitly flags this doesn't explain agents wedging *before* any session exists (the
dialog fires at `query_end`, not on a cold pane), which stays open/unproven. Nothing in
the thread proposes or attempts a generic detector; it is entirely about this one dialog.
