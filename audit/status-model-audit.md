# Status model audit — what switchboard actually tracks, and whether "idle" survives

Read-only audit. No production code changed. Evidence is file:line throughout; DESIGN-TRUTH.md
citations are quoted, not paraphrased, since it is the only trusted document here.

## Answer, up front

**Andrew has settled Part 2's question directly: idle stays as one of the true statuses.**
`idle, working, failed, blocked, done` is the fixed set — a waiting orchestrator (top or not) is
`idle`, not `done`, because its own task is not finished, only pending on others; a separate
`waiting` state was explicitly rejected as unneeded complexity. What follows redefines Part 2
around that: precise meaning and setter for each of the five, and the mechanism — already present
in the code, just not currently framed this way — that tells a legitimately-idle agent apart from
one that quietly quit, given that both present identically at the pane level. Part 1 (the audit
of what exists today) is unchanged below.

The working+stalled pair Andrew originally saw is real, reproducible from the code, and is not a
logic bug — it is two vocabularies (the store's self-report and a computed drift label) rendered
on the same row without ever silencing the first one once the second fires. See Part 1.3.

---

## Part 1 — what we have

### 1.1 Every status, and where it lives

**A. The store's `state` column** — `switchboard/store.py:145` (`agents.state`), grouped in
`defaults/settings.toml:127-144`. A closed, four-word vocabulary:

```
working | blocked | done | failed
```

This is the only status column that persists row-for-row and the only one `sb wait --for` accepts
verbatim (`switchboard/status.py:99-103`, comment on `GONE_STATE`). `[states]` in
`defaults/settings.toml:127-144` groups these words into policy sets used everywhere else:
`running = ["working"]`, `finished = ["done", "failed"]`, `live = ["working", "blocked"]`.

**B. herdr's state** — `switchboard/herdr.py:82-83`:

```python
IDLE, WORKING, BLOCKED, UNKNOWN = "idle", "working", "blocked", "unknown"
```

This is what the OTHER agent (`truth-status`) is separately auditing for correctness; I did not
re-verify it. It surfaces into switchboard as `AgentStatus.herdr_state`
(`switchboard/status.py:230`). `status.py:88-90` documents a fifth *display-only* value herdr
hands back, `done` — "idle and not yet looked at" — which switchboard treats as identical to
`idle` for every purpose here (`IDLE_LIKE = frozenset(config.setting("states.idle_like"))`,
`defaults/settings.toml:144`: `idle_like = ["idle", "done"]`).

**C. `AgentStatus`, computed per request** — `switchboard/status.py:221-367`. Never stored (one
exception, C below). Built by joining A and B in `status.collect`
(`switchboard/status.py:411-573`):

- `stalled: bool` — data field, computed at `status.py:539-540`
- `gone: bool` — data field, computed at `status.py:541`, and this ONE is written back
  (`_record_gone`, `status.py:619-657`)
- `blocked` (property, `status.py:248-250`) — mirrors the store's `state == "blocked"`
- `at_prompt` (property, `status.py:252-260`) — `herdr_state == BLOCKED`, i.e. a permission
  prompt sitting in the TUI; unrelated to the store's `blocked`
- `finished` (property, `status.py:262-264`) — `state in FINISHED`
- `waiting_to_be_rung` / `ringable` (properties, `status.py:266-306`) — mailbox-side drift, a
  third vocabulary living in the mailbox rather than the pane (module docstring,
  `status.py:34-54`)
- `needs_human` (property, `status.py:307-320`) — OR of five of the above
- `archived` (property, `status.py:322-351`) — a pure rendering fact, never stored, explicitly
  documented as unsafe to store ("the moment anything stores this, that argument is gone and so
  is the safety" — `status.py:330-331`)

**D. `awaiting_task`** — a store column (`store.py:192-199`), FACT not guess: set at spawn when
an agent got only a placeholder task, cleared by the first message it receives
(`store.py:1341-1344`). It is DESIGN-TRUTH's own named exemption ("unless it is awaiting
instructions", DESIGN-TRUTH.md:131) and is read defensively by `status.collect`
(`status.py:516`).

**E. The board's own rendering vocabulary** — `switchboard/board.py`:
- `glyph()` (`board.py:155-176`) — one of `✗ ◐ ◌ ○ ? ●`
- `note()` (`board.py:188-209`) — one-line label: `GONE`, `AT PROMPT`, `BLOCKED — <why>`,
  `STALLED — idle <age>`, `<n> unread`, `done: <summary>`, or the task text
- the raw STATE column (`board.py:277-291`, `status.py:1091-1101` for `sb status`'s own table) —
  prints `a.state` (vocabulary A) **verbatim, unfiltered by drift**

**F. `_busy()`** — `switchboard/broker.py:4002-4009`. A fourth, independent read of herdr's raw
state (`== WORKING`), used only to gate `when-idle` delivery (`broker.py:4242`,
`broker.py:3198`). It does not go through `AgentStatus` at all — a fifth place "is this agent
idle right now" gets answered, separately from `stalled`/`herdr_state`/`IDLE_LIKE`.

**G. Event-log kinds** — history, not state, but worth naming since they record transitions the
columns above don't: `done`, `blocked`, `gone` (`status.py:656`), `stop_gate_blocked`,
`stop_gate_waived`, `stop_gate_capped` (`hooks.py:237,244,246`), `reconcile_waived`
(`broker.py:4428`), `done_with_live_children` (`broker.py:3402`).

### 1.2 Fact recorded vs. guess computed

| Name | Kind | Set by |
|---|---|---|
| `state` = working | **fact** | `sb delegate`/`sb start` spawn, `_revive` |
| `state` = blocked | **fact** | agent's own `sb block` (`broker.py:3448`) |
| `state` = done | **fact** | agent's own `sb done` (`broker.py:3395`) |
| `state` = failed | **guess, disguised as a fact** | `status._record_gone` ONLY — no agent command ever sets it (verified: no `set_state(..., "failed")` outside `status.py`) |
| `awaiting_task` | **fact** | spawn placeholder / cleared on first message (`store.py:192-199`) |
| `herdr_state` | **fact, about the pane** (per herdr, whose own accuracy is out of scope here) | herdr's own detector |
| `stalled` | **guess** | computed every call, never persisted (`status.py:539-540`) |
| `gone` | **guess → fact**, debounced | computed, then written back once `GONE_CONFIRM_GRACE` survives it (`status.py:576-657`) |
| `at_prompt`, `finished`, `needs_human`, `waiting_to_be_rung`, `ringable`, `archived` | **guesses** | all derived properties, `status.py:248-351` |

The one blurred line is `failed`: it sits in the same closed, four-word column as three genuine
self-reports and reads exactly like one on the board and in `sb wait --for`, but no agent command
in this codebase can ever produce it — it is 100% inferred. `status.py:99-108` explains the
*reason* it was folded into the state column (a fifth word costs every reader of that column),
but the audit's point stands: one cell in vocabulary A is actually a vocabulary-C guess wearing
vocabulary A's clothes.

**Authoritative status**: the store's `state` column (A) is the only durable, agent-controlled
fact. Everything else — herdr's state, and every `AgentStatus` property — is recomputed from
scratch on every `collect()` call and is authoritative only for that instant.

### 1.3 Where they contradict — the working+stalled row

Reproduced directly from the code, not inferred:

- `switchboard/board.py:277-291` (and `status.py:1091-1101` for `sb status`) print the raw store
  `state` in its own column — `"working"` — with **no gate on `stalled`**.
- `switchboard/board.py:201-202` (`note()`) prints `STALLED — idle <age>` on the **same row**,
  once `a.stalled` is true.

So one row reads `STATE=working … STALLED — idle 12m`, which is exactly the contradiction Andrew
saw. This is **not a bug in the sense of an unintended defect** — `status.py`'s own module
docstring (lines 1-16) names this precise pair as the whole reason the file exists:

> `store: working  herdr: idle  →  STALLED` ... We deliberately do NOT repair it: marking it done
> here would fabricate a summary its parent never received ... Surfacing beats guessing (C9).

The design intentionally keeps `state` unrewritten (except by the agent itself or by confirmed
`gone`) and computes `stalled` as an independent, honest label for the disagreement. What was
never designed is the **display**: nothing suppresses or folds the raw `working` word once
`stalled` fires, so the row shows both labels un-reconciled instead of one coherent label. It is
a structural consequence of two vocabularies (self-report vs. computed drift) sharing a row, made
worse by a presentation gap, not a data-model defect.

Other pairs checked and found **not** contradictory, by construction:
- `stalled` and `gone` are mutually exclusive: `stalled` requires `alive` true, `gone` requires
  `alive is False` (`status.py:539-541`).
- `stalled` and `awaiting_task` are mutually exclusive: `stalled`'s formula explicitly excludes
  `awaiting_task` rows (`status.py:539-540`, `and not awaiting`).
- `finished` (state=done/failed) and `stalled` cannot co-occur: `stalled` requires
  `state in RUNNING`, and `RUNNING = ("working",)` only (`defaults/settings.toml:132`), disjoint
  from `FINISHED`.

One near-miss worth flagging for whoever owns the mailbox side: `waiting_to_be_rung`/`gone` can
briefly overlap — a `gone` agent can still show `unread`/`undelivered` mail until
`broker._clear_unreadable_mail` writes `undeliverable_at` (`status.py:665-671` documents a real
incident, `2026-08-09-233230`, where this left mail stuck in NEEDS YOU with no recipient). Not
newly discovered here, just confirmed still present in the current joins.

### 1.4 Consumers — who reads each status, and what breaks if the model changes

| Consumer | Reads | File:line |
|---|---|---|
| `sb status` / `sb board` render | `state`, `stalled`, `gone`, `at_prompt`, `blocked`, `unread`, `waiting_to_be_rung`, `archived` | `status.py:1065-1276`, `board.py:155-291` |
| Reconciler (phase 3.5) | `stalled`, `awaiting_task` (via `collect`), live-children check | `broker.py:4380-4437` |
| Stop gate (phase 3.8) | `state in REPORTED`, `awaiting_task`, live-children, "already nudged" | `hooks.py:198-247` |
| `sb cleanup` | `state in FINISHED` | `broker.py:3604`, `broker.py:3997`, `store.py` FINISHED gates |
| Delivery mode selection (`when-idle`) | raw herdr `WORKING` via `_busy()`; `blocked` for mail-hold | `broker.py:4002-4009`, `broker.py:4181-4242` |
| `--needs-me` filter | `AgentStatus.needs_human` | `status.py:307-320`, `status.py:834-865` |
| `sb wait --for` | raw `state` word, verbatim | `status.py:99-103` (documented contract) |
| Collector's doorbell | `AgentStatus.ringable` | `status.py:278-306`, `collector.py:223-349` |

Any change to the model has to keep all eight of these fed with what they currently key on:
`state` (self-report), `awaiting_task` (self-report), `stalled`/`gone` (computed drift), and raw
herdr `WORKING`/`BLOCKED` (pane observation used directly, bypassing `AgentStatus`).

---

## Part 2 — the five true statuses, and idle vs. stalled

**Andrew's ruling, taken as fixed:** the true statuses are `idle, working, failed, blocked, done`.
A waiting orchestrator — top or not — is `idle`, not `done`: its own task is not finished, it is
only pending on others. No separate `waiting` state; he rejected that as complexity with no
payoff. This section defines each of the five precisely, says what sets it, and — the part that
actually needs solving — shows how `idle` is told apart from a silent quit, since a waiting
orchestrator and an agent that quietly stopped reporting look identical at the pane level: both
are "task open, pane not running a turn."

### The five, precisely

| Status | Means | Set by |
|---|---|---|
| **working** | A turn is actively running in the agent's pane right now. | herdr's own detector, read live — not written by switchboard at all (`herdr.py:82-83`, `_busy()` at `broker.py:4002-4009`) |
| **idle** | The agent's task is still open (it has not called `sb done` or `sb block`) and no turn is currently running in its pane. Covers both the legitimate case (waiting on children, or on its first task) and the illegitimate one (quietly stopped without reporting) — see below for how those are told apart. | Computed: store `state == "working"` (i.e. task still open) **and** herdr reports idle-like (`status.py:88-91`, `IDLE_LIKE`) |
| **blocked** | The agent stopped itself and is waiting on a human answer. | agent's own `sb block` (`broker.py:3425-3450`, `store.set_state(..., "blocked")`) |
| **done** | The agent reported its task complete. Stays open — a parent still owns cleanup — but nothing is pending on it and nothing pings it. | agent's own `sb done` (`broker.py:3352-3423`, `store.set_state(..., "done")`) |
| **failed** | The agent's turn ended and its pane is gone; nobody will ever hear from it again the way it stood. | **system-inferred only** — `status._record_gone` (`status.py:619-657`), after `_confirmed_gone` debounces a continuous absence past `GONE_CONFIRM_GRACE` (`status.py:576-616`). See the flag at the end of this section: no agent command produces this today. |

`working` and `idle` are two readings of the same underlying store fact (task still open,
`state == "working"` in today's schema) — which one is true is decided entirely by herdr's
pane observation, recomputed on every read, never stored. `blocked`, `done`, and `failed` are
each a terminal-ish write: two are agent self-reports, one is a system verdict. This is the two
axes the brief invited me to name if the evidence supported it, and it does — but per Andrew's
ruling they are not exposed as two separate fields. They collapse into one five-way status by a
fixed rule: **if the task is still open, show whichever of working/idle herdr's pane observation
says; otherwise show the terminal report.** That collapse is exactly what the code already
computes as `AgentStatus.stalled`'s precondition (`running and alive and hstate in IDLE_LIKE`,
`status.py:539`) — today it is a side-flag bolted onto a row that still says `working`; under this
model it becomes the primary label.

### Telling idle apart from stalled

"Stalled" is not a sixth status. It is what today's code already computes: `idle`, **without a
legitimate reason to be idle**. The mechanism that supplies "legitimate reason" already exists,
built for the reconciler and the stop gate, and needs no new machinery — it needs to be read as
answering exactly this question:

An agent is `idle` (task open, pane not running a turn). Ask, in order:

1. **Has it never been given anything yet?** `awaiting_task` is true
   (`store.py:192-199`, cleared on the first message it receives). → **Explained: idle, awaiting
   instructions.** Nothing pings it.
2. **Does it have a live child?** `_has_live_child` — a row with `parent = this` and
   `state IN ('working','blocked')` and not ended (`hooks.py:160-165`, reused by the reconciler at
   `broker.py:4427`). → **Explained: idle, waiting on children.** This is the case Andrew named
   directly — top or not, an orchestrator with work still out is idle, not done, and this is the
   fact that makes it so. Nothing pings it either; the moment its last child resolves, this
   exemption lifts and it is re-evaluated from the top on the next read.
3. **Is it new enough that "idle" might just mean "hasn't started yet"?** Two separate grace
   windows cover the two ways a fresh agent can look idle before it has ever really run:
   `spawning` (`session_id IS NULL` and within `SPAWN_GRACE` of creation, `status.py:504`) and
   `starting` (`session_id IS NULL` and within `STALL_GRACE` of its last activity,
   `status.py:528`). → **Explained: idle, still starting up.** Not pinged; re-checked every read
   until the window closes or a session id appears.
4. **None of the above.** → **Unexplained.** This is what the code currently names `stalled`
   (`status.py:539-540`): idle with no live child, not awaiting its first task, and past both
   spawn/start grace windows. Under this model it is not a different status from `idle` — it is
   `idle` that has run out of excuses. This is the one the reconciler pings
   (`broker.py:4380-4437`) and the stop gate refuses to let a turn end into
   (`hooks.py:198-247`), and it is the one `sb status`/`sb board` should flag, because it is the
   only one of the four that means something might actually be wrong.

So the waiting orchestrator and the silent quitter present identically at the pane
(`state=working, herdr=idle`) and are told apart by exactly one thing: whether a live child,
an unstarted task, or a startup grace window explains the idleness. Structurally this is the same
predicate `AgentStatus.stalled` already computes and the reconciler/stop-gate already exempt
against (§1.4) — nothing here is new machinery. What changes is which label is primary: today the
row still says `working` and `stalled` is a bolted-on warning; under the five-status model the row
says `idle`, and "explained" vs. "unexplained" is what used to be called `stalled` vs. not,
demoted from a rival status to a qualifier on `idle`.

### What would have to change, and how big

Small, and almost entirely in the read/display path — the write path barely moves:

- **No new store column.** `state` keeps its four written values (`working`, `blocked`, `done`,
  and system-written `failed`); `working` continues to mean "task open," exactly as today.
- **The computed layer is what changes.** `AgentStatus` (or its renderer) needs to derive the
  five-way label — `idle` vs. `working` for an open task, per herdr; `blocked`/`done`/`failed`
  passed through — instead of exposing the raw `state` word next to a separate `stalled` boolean.
  This is the fix Part 1.3 already identifies as needed to kill the working+stalled contradiction
  Andrew saw: `board.py:277-291`'s STATE column and `status.py:1091-1101`'s table both print raw
  `state` unconditionally today. Under this model they'd print the five-way label instead, with
  step 4 above (`unexplained idle`) as the thing that gets a `<< STALLED`-style flag next to it —
  same visual seriousness as today, attached to the right word.
- **Reconciler and stop gate are already correct and need no logic change** — `_has_live_child`,
  `awaiting_task`, and the grace windows are precisely the "explained idle" test above; they just
  currently gate a flag called `stalled` rather than a status called `idle`. Renaming/reframing
  only, not new predicates.
- **`sb wait --for`** currently accepts the store's four written words verbatim (`status.py:99-
  103`). If it should also accept `idle` as a wait target — waiting for an orchestrator to become
  idle-with-live-children-resolved, for instance — that is new surface, not implied by anything
  audited here; flagging it rather than assuming it.

### Flag for Andrew, not resolved here

`failed` is one of the fixed five, and nothing in the current code lets an agent produce it
itself — only `sb done` and `sb block` exist as self-report verbs; `failed` is exclusively the
system's inference from a pane going away and staying gone (§1.2, `status.py:619-657`). If the
intent is that an agent can self-report "I failed" (distinct from the system detecting it quit
without a trace), that verb does not exist yet and this audit does not decide whether it should.
