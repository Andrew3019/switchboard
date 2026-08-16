# Adversarial verification — STALLED vs idle

Read-only. No code touched, nothing committed. Everything below I checked myself in
`switchboard/status.py`, `switchboard/board.py`, `switchboard/richboard.py`,
`switchboard/broker.py`, `switchboard/collector.py`, `defaults/settings.toml`,
`DESIGN-TRUTH.md`, plus two live runs:

- `./bin/sb status --json` against the live fleet (one instant, 36 rows).
- A scratch harness driving the **real** `status.collect` + `richboard.needs_list` +
  `board.marker` over a temp store and a fake herdr — the same shape `tests/test_status.py`
  uses. Four scenarios, output quoted inline below. Script kept out of the repo at
  `<scratchpad>/probe.py`.

---

## 1. `stalled` is `idle` minus three excuses, same tick, no lag — **CONFIRMED**

`status.py:908-912` and `:933`, one expression, one loop iteration:

```python
excuse = ("awaiting first task" if awaiting
          else "waiting on children" if name in live_parent
          else "starting up" if starting
          else None)
idle = bool(running and turn_over and alive is not False)
...
stalled=idle and excuse is None,
```

No duration term anywhere in it. I looked for one specifically:

- `STALL_GRACE` (`status.py:227`) appears in `stalled`'s inputs only via `starting`
  (`status.py:885`), and only for rows with `session_id IS NULL`. It *widens* the excuse
  set; it cannot delay STALLED for an agent that has ever run an `sb` command.
- `TURN_STALE_GRACE` / `TURN_DOUBT_GRACE` (`:270-271`) feed `signal_drift` / `turn_doubted`
  (`:485`), a different predicate.

Live proof — an ordinary worker whose turn ends, scenario C:

```
w1  state=working  disp=idle  stalled=True  excuse=None  marker='STALLED — idle 0s'
NEEDS YOU -> ['w1']
```

**Zero seconds.** The code says so about itself, too: `broker.py:4014-4020` —
"`stalled` is `idle and no excuse`, with no idle-duration term in it anywhere … makes it
true at zero seconds". That docstring is untrusted, but scenario C is the same claim
executed.

One thing the other report got right and worth keeping: `states.running = ["working"]`
(`defaults/settings.toml:150`), so `blocked` and `done` rows are never `idle` and never
`stalled`.

## 2. STALLED ⟹ NEEDS YOU, with one gap — **PARTLY (the gap is real; the report's example of it is wrong)**

Predicate direction holds: `needs_kind` (`richboard.py:227-231`) returns `"idle"` for every
`a.stalled`, and `needs_list` (`:296-298`) only ever *removes* — `busy_below`.

**The claimed example is REFUTED.** The other report says the gap is "a lead whose child is
itself idle-with-a-working-grandchild" (its §4 and §6). That shape cannot happen.
`live_parent` (`status.py:796-798`) is built from the **raw store state**, and an idle
agent's row still says `working` — so a lead with *any* open direct child is excused,
whatever that child is doing. Scenario A, real `collect`:

```
A  lead -> mid(open, idle) -> kid(working)
   lead  state=working  disp=idle  stalled=False  excuse=waiting on children  marker=''
   mid   state=working  disp=idle  stalled=False  excuse=waiting on children  marker=''
   NEEDS YOU -> []
```

Nobody is STALLED. The row the report proposes to fix does not exist.
(`tests/test_richboard.py:305-311` builds that shape by hand with `stalled=True` on both —
a fixture `collect` cannot produce.)

**A different gap IS real.** It needs the intermediate to be *finished* while a grandchild
under it still runs — legal, per `broker.done` ("reporting done with children still working
stays legal"). Scenario B:

```
B  lead -> mid(done) -> kid(working)
   lead  state=working  disp=idle  stalled=True  excuse=None  marker='STALLED — idle 0s'
   NEEDS YOU -> []
```

Row reads STALLED, absent from NEEDS YOU. So the gap survives — via a shape the other
report did not identify, and its §6 fix sketch would still close it, for the wrong stated
reason.

**Two more ways to be STALLED and not in the section, both missed by the other report,**
both display rather than predicate: `_needs_block` truncates at `NEEDS_MAX`
(`richboard.py:679, 697-699`), and a short pane sheds the section a line at a time and then
entirely (`richboard.py:499-507`).

## 3. Idle-but-not-stalled in practice — **PARTLY**

True for leaves, false for leads, and the live board is the counterexample.

`sb status --json` on the live fleet, this instant: 36 rows, **0 stalled**. Every open row
that was idle carried an excuse:

```
github-issues         working  idle  stalled=False  excuse=waiting on children
board-awaiting-keypress working idle stalled=False  excuse=waiting on children
stalled-vs-idle       working  idle  stalled=False  excuse=waiting on children
```

Everything else was either `working` or `done` — and a `done` row is not idle at all
(`state` not in `RUNNING`), so it never enters this question. That matters: the idle set is
already small, because an agent that reports properly leaves `working` behind.

So "nearly every idle row reads STALLED" is right for a leaf that ends a turn (scenario C)
and wrong for the lead/orchestrator shape, which is most of what was on the board when I
looked. One instant, one fleet — I did not sample over time.

The sharper finding is what *else* lands in the unexcused set. Scenario D — an agent that
ran `sb tell --needs-reply` and ended its turn to wait, exactly as the protocol tells it to:

```
D  w1 asked --needs-reply and ended its turn
   w1  state=working  disp=idle  stalled=True  excuse=None  marker='STALLED — idle 0s'
   NEEDS YOU -> ['w1']
```

Doing the right thing, marked STALLED, summoning Andrew. The other report guessed the
excuse list "may be too narrow" and named a dispatcher between tasks; this is a concrete,
protocol-sanctioned shape it missed.

## 4. What the board actually renders — **REFUTED (there is a clear visible distinction)**

Not the same to a human scanning. For an idle-excused row versus a stalled one:

| | glyph | name | state col | tail |
|---|---|---|---|---|
| excused | `●` green (`board.py:181-185`) | normal | `idle` | dim `waiting on children` (`richboard._excuse`, `:180`; `board.tail_note`, `:233-239`) |
| stalled | `◌` yellow (`board.py:177-180`) | bold (`wants_you`, `:200`; `richboard.py:630`) | `idle` | yellow `STALLED — idle 12m` (`board.marker`, `:215-216`) |

Plus a NEEDS YOU line for the stalled one. Both rows do say `idle` in the state column
(`display_state`, `status.py:387-438`) — that word alone does not separate them, but three
other channels do. Under width pressure the excuse is the first thing dropped and the
STALLED word is reserved (`richboard.tail_forms`, `:146-149`; `squeeze`, `:195-211`) — so a
narrow pane loses the calm half, never the alarm.

Andrew's complaint is therefore not "they look identical". It is that the alarming set is
too big.

## 5. Intent per DESIGN-TRUTH — **PARTLY, and the other report leans the wrong way**

`DESIGN-TRUTH.md` contains **no** occurrence of "stalled", "STALLED", or "NEEDS YOU"
(grepped, case-insensitive). The only line on point, `DESIGN-TRUTH.md:155-159`:

> **A reconciler runs on a loop — maybe the same loop `sb board` runs on.** If an agent is
> idle and neither blocked nor done, it pings that agent to say it should probably report
> done or blocked, unless it is awaiting instructions. The ping goes to the agent itself
> rather than to its parent, because the agent has more context on what its true status is.
> That is how we avoid stale idle agents. — confirmed 2026-08-09

Two things follow.

- **The predicate matches.** `broker.reconcile` (`:5384-5397`) iterates exactly
  `a.stalled`, pings the agent (not the parent), and the `awaiting_task` exemption is
  DESIGN-TRUTH's own. `collector.run_reconciler` (`:290-312`) fires it within one
  `RECONCILE_GAP` (10s) of a name going stalled. Code follows the trusted doc.
- **The conclusion the other report draws does not.** DESIGN-TRUTH's designated first
  responder to "idle with no excuse" is the **reconciler**, automatically — not a human. It
  says nothing that makes STALLED a summons. The "a human should look" reading comes from
  `status.py`'s module docstring and `richboard.needs_kind`'s docstring, which are
  untrusted, and the other report cites them as if they settled it (its §5).

---

## Verdict

**Andrew's complaint points at a real defect — but not the one the other report proposes to
fix, and its "the complaint dissolves" conclusion should not be acted on.** The mechanics
the report describes are mostly right: `stalled` really is `idle` minus three excuses on the
same tick, and STALLED really does imply NEEDS YOU by predicate. What that misses is the
consequence. STALLED fires at *zero seconds* of idleness, its excuse list covers only three
structural shapes, and the board summons Andrew for every one of them in the same instant —
including for an agent waiting on an answer it explicitly asked for (scenario D), and
including at the exact moment the reconciler is already about to ping it, which is what
DESIGN-TRUTH says should handle it. Meanwhile the one concrete fix the report sketches (the
subtree check) is motivated by a shape that cannot occur (scenario A); a differently-shaped
gap does exist (scenario B), but it is narrow and it makes the board *quieter*, not the
noise Andrew reported. The change worth discussing is on the other side: NEEDS YOU
membership should require more than "idle 0s with no excuse" — an idle-duration floor, or
"the reconciler already pinged it and it stayed quiet", or an excuse for an agent waiting on
a reply it asked for. Which of those is a design decision for Andrew, not a bug fix to pick
myself.

**Not checked:** `hooks.py`'s stop gate beyond what `broker._has_live_child` mirrors; how
often the four scenarios occur over time (one live sample only); whether `NEEDS_MAX`
truncation ever bites in Andrew's actual pane size.
