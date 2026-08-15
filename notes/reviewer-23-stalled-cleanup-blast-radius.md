# Adversarial review of `65dcd53` — lens: what this change costs when it is wrong

reviewer-23. Read-only: no source file touched, no commit made.

**Verdict: do not land as it stands.** The sweep bar is not the predicate the task
believed it was specifying. `status.stalled` is only debounced in the crashed-turn-edge
case; for a healthy agent that ended its turn correctly it is true at **zero seconds
idle**, with no herdr agreement required. A bare `sb cleanup` — which `DESIGN-TRUTH.md`
and `roles/lead.md` tell leads to run *constantly* — now closes the pane of any child
that ended a turn and is waiting to be poked.

## How I checked

- Read `65dcd53`, `Broker.cleanup` (broker.py:3603-3911), `status.collect` /
  `AgentStatus.stalled` / `.turn_doubted` (status.py:380-936), `Broker.reconcile`
  (4614-4698), `Broker.restore` (3961+), `cli.py`'s `cleanup` wiring (250-257, 1055),
  `defaults/settings.toml` `[timeouts]`, `hooks.py:374,393`.
- Ran the repo suite: `1237 passed`. The implementer's claim holds.
- Ran five probe scenarios against the repo's own test harness from a scratch file
  outside the checkout
  (`<scratchpad>/test_hazards.py`, subclassing `tests/test_broker.py:BrokerTest`, so the
  fake herdr is the one already in the repo — nothing was taught a new trick). Output
  quoted verbatim below.
- **I did not run a live clone.** Everything below is code plus unit-level probes plus
  the project's own documented statements. Findings 1, 2, 4 and 5 are demonstrated by
  probe; finding 3 is reasoned from status.py's and settings.toml's own text and is not
  demonstrated.

## Finding 1 — the sweep bar has no debounce for the ordinary case, and no floor at all

`stalled = idle and excuse is None` (status.py:883). `idle = running and turn_over and
alive is not False` (862), and `turn_over = (turn == TURN_IDLE) if turn is not None`
(849). **There is no idle-duration term anywhere in `stalled`.** The only clock in it is
`starting`, which needs `session_id IS NULL` (835).

The 45-minute debounce the task and the new docstring both describe
(broker.py:3727-3731, task file lines 40-45) exists only on the path where the turn edge
is *stuck at `working`* — there `stalled` is false until `_forget_turn` NULLs the edge.
The Stop hook writing `TURN_IDLE` (hooks.py:374) is the *normal* end of a turn, and it
makes `stalled` true immediately.

Probe A — a `working` row, session claimed, Stop hook fired correctly, no children, no
mail, herdr reading `idle`:

```
[A] age=0s idle=0s stalled=True excuse=None turn='idle'
    bare `sb cleanup` (no --force) -> closed ['kid'], pane w1:p1 closed
```

Concrete sequences that produce exactly that row, all of them healthy:

- a child that ran `sb tell parent "..." --needs-reply` and ended its turn to wait for
  the answer;
- a child that backgrounded a long shell command and ended its turn — the implementer
  observed this shape live and reported it;
- any agent that ended a turn and is waiting for its next poke, once `awaiting_task` has
  been cleared by its first message.

The three excuses (status.py:858-861) cover *awaiting the first task*, *waiting on
children*, and *the first 72 s of an agent with no session id*. None covers "waiting for
a reply", which is the protocol's own idiom.

Probe A2: herdr is not a veto here. With `turn='idle'` and herdr reporting the pane
`working`, our own edge outranks it (status.py:849) and the sweep still closes:
`[A2] swept=['kid']`.

Before this change the cost of this false positive was one `reconcile` ping. It is now
the pane.

## Finding 2 — closing one row makes its parent sweepable on the next sweep

`live_descendants` (gate 3) is computed once, up front, so a parent is safe *within* one
invocation. But "waiting on children" is the parent's only excuse, and the sweep just
removed the child that supplied it.

Probe B, two consecutive human sweeps, both bare, neither forced:

```
[B] before: orch stalled=False excuse='waiting on children'; kid stalled=True
[B] sweep 1 closed ['kid']
[B] after:  orch stalled=True  excuse=None
[B] sweep 2 closed ['orch']
```

So one false positive at a leaf unwinds the branch above it, one level per sweep, and
each level's refusal reads as an ordinary tidy-up. `DESIGN-TRUTH.md:372` tells leads to
clean up "aggressively — probably literally every agent that is done", and
`roles/lead.md:194` says "use it constantly", so repeated sweeps are the expected usage,
not a pathological one.

## Finding 3 — the named bar spends the one guarantee the design is built on

`turn_doubted` (status.py:513-515) is `turn == working` AND herdr alive AND
`herdr_state in IDLE_LIKE` AND `idle >= 30 min`. Its own docstring closes with: *"Herdr's
reading is intermittent, so one disagreement must never be enough to move a row — that
is the finding this design is built on rather than around."* `settings.toml`'s
`turn_stale_grace` comment says the same thing about the 30-minute half: *"this
deliberately does NOT decide anything on its own; it only says when a row becomes worth
asking herdr about. See `turn_doubt_grace`, which is what decides."*

`given_up_on` uses `turn_doubted` to decide. Until now its only consumer was
`_forget_turn`, behind `_sustained(..., TURN_DOUBT_GRACE)` — 15 minutes of *continuous*
disagreement, and the worst outcome of getting it wrong was a mistaken ping.

Two of the project's own measurements say this bar fires on live agents:

- `settings.toml`: a live agent goes without an `sb` command inside one turn for 20.6 min
  at p99 and **139 min at p99.9** — so the 30-minute half does not exclude working
  agents, and is documented not to.
- `status.py:449-451`: herdr's `idle` "is what a live agent mid-tool-call reads as
  today".

Sequence: a worker 35 minutes into a long build or test run, no `sb` calls in that turn;
its parent, having watched the board show STALLED, runs `sb cleanup worker-7`; the
single herdr reading taken at that instant says `idle`. The pane is closed mid-tool-call.
No `--force` was typed and no second reading was required. `turn_doubt_grace` exists
precisely because that first reading is expected to be wrong sometimes.

I did not demonstrate this one — a unit test would only re-encode my reasoning, since the
fake herdr cannot be intermittent in the way the real one is. It rests on the two quoted
documents and on `turn_doubted`'s definition.

## Finding 4 — closing is not always free, and the case where it isn't is swept first

`Broker.cleanup`'s docstring and `protocol.md:219` both promise "closing costs only the
pane… `sb restore` brings an agent back". `restore` refuses outright without a session id
(broker.py:3977). An agent gets one only from `_claim_session`, i.e. from its first `sb`
command (status.py:805) — so a freshly delegated worker that spends its first minutes
reading files has none, and its only protection is `starting`, which lasts **72 s**
(`STALL_GRACE`).

Probe C — 200-second-old row, no session id, no turn edge, herdr reading `idle`:

```
[C] stalled=True excuse=None session=None
    bare `sb cleanup` -> closed ['kid']
[C] restore -> kid has no session id; nothing to restore
```

That is the one class where the close is unrecoverable, and it is the class with the
weakest evidence behind the verdict: no turn edge of our own, one herdr reading, 72
seconds of grace.

## Finding 5 — `given_up_on` never asks whether herdr was reachable

`snap.herdr_error` is not consulted. When `agent list` fails, `collect` degrades to
`alive=None` and every row whose turn edge reads `idle` is *still* `stalled`, because
that path needs no herdr input at all.

Probe E — `agent list` raising while pane operations still work:

```
[E] herdr_error='[timeout] agent list timed out' alive=None stalled=True
[E] sweep closed ['kid']; panes closed ['w1:p1']
```

A *total* herdr outage is self-limiting (the `release_agent`/`close_pane` call raises and
the row is refused), but a list-only failure is not. Compare `live_descendants`, which is
deliberately store-only "because a hiccup that read as 'no live children' would wave
through exactly the close this exists to stop" — the same argument applies here and is
not made.

## Also: the snapshot goes stale and nothing re-checks before the close

One `collect` is taken at the first unfinished candidate and reused for every later one,
while each close costs two herdr round trips. `reconcile._nudge` re-asks `self._busy(who)`
at act time, and says why: *"the snapshot is a few milliseconds old, and an agent that has
started a turn since it was taken must not be pinged at all."* The sweep does no such
re-check, and its act is destructive rather than a ping.

The systematic version: the collector's `reconcile` pings exactly the rows this sweep
targets, and the ping leaves no unread mail (it is a prompt, not mail) and is logged
against no agent. So a row pinged at T, awake and working at T+2s, is closed at T+3s by a
sweep whose snapshot was taken at T−1s. Not demonstrated — it is an inter-process race —
but nothing in the code prevents it.

## Hazards I looked for and the code already prevents

- **Mail arriving after the snapshot.** Gate 4c reads mail live (`store.unread_for`,
  3806), not from the snapshot, so a `sb tell` landing between the collect and the close
  does hold the row. The mail gate genuinely stands on its own, as claimed.
- **Sweeping a parent over a live child.** `held` is computed before the loop and from
  the store alone, so no ordering inside one invocation can break the invariant. Probe B
  sweep 1 left `orch` alone, correctly.
- **Path collapse of the sweep/named asymmetry.** Checked all four: `names=[]` →
  `bool(names)` is False → sweep bar; `--force` with no names raises before anything is
  read (3675); an unknown name raises `KeyError` before anything is closed (3669);
  `--dry-run` still takes the collect but writes nothing and logs no `cleanup_stalled`
  (the event is after the `dry_run` continue, 3837/3848); `--json` is output only
  (cli.py:1055). The asymmetry is implemented as specified.
- **`reap=False`.** Correct, and for the reason given: the alternative would let the
  gate's own reading write `failed` rows and clear turn edges mid-loop.
- **Telling a stalled sweep from a normal close afterwards.** Probe D:
  `cleanup_stalled{"state":"working","named":false}` is logged immediately before
  `cleanup{"forced":false}`. The event record does answer the question. One caveat worth
  knowing: the *row* ends `state='done'` with `summary=None`, so the board and a parent's
  `sb status` cannot tell a swept live agent from a finished one — only `sb log` can.

## One more, small

`cli.py:250-252` still describes the verb as "close finished agents… closes every
finished agent in your subtree", and `protocol.md:219` — which every agent in the fleet
reads — says the same. After this change a bare sweep also takes rows nobody reported an
end for. Not a wording nit: it is the sentence a lead relies on when it sweeps constantly.

## What I would want before landing

Not my call to redesign, but the shape of the gap is narrow: the sweep bar needs to
select the case the bug was actually about — a row whose turn edge switchboard itself
gave up on and NULLed (`turn IS NULL` after `_forget_turn`), or `stalled` with a real idle
floor under it — rather than `stalled`, which is also true of every agent that ended its
turn one second ago. The named bar needs the debounce back, or `--force`.
