# STALLED vs idle — finding (no fix shipped)

Andrew asked: is every idle agent effectively shown as stalled on `sb board`, and should
only an idle agent that actually reaches NEEDS YOU be called "stalled"? He authorised
shipping a fix end to end **only if** the finding is clear and the intent reads as correct.

**It is not, so nothing was shipped.** No code was touched. Two read-only agents
investigated; the second ran the real `status.collect` + `richboard.needs_list` +
`board.marker` over a temp store and a fake herdr, and sampled the live fleet. Their reports
are `notes/stalled-scout2-stalled-vs-idle.md` (first pass) and `notes/verify-stalled-vs-idle.md`
(adversarial check, which overturned the first pass's conclusion). Where they disagree, the
second is the one with live proof behind it.

## What the two states actually are

`stalled` is not a delayed, worse version of `idle`. It is the *same* idle boolean computed
in the same expression on the same tick (`status.py:908-933`), minus three narrow excuses:

- awaiting a first task,
- has a live **direct** child,
- still starting up.

There is no idle-duration term anywhere in it. An ordinary leaf agent that ends a turn is
STALLED at **zero seconds** idle, and lands in NEEDS YOU in that same instant.

## Andrew's two claims, separated

- **"all idle are stalled"** — true for leaf agents, false for leads. A lead with any open
  direct child is always excused, so on the live fleet at the moment we sampled, 36 rows
  carried **zero** stalled. The alarming set is small in a healthy fleet and fires
  immediately for any worker that ends a turn without reporting.

- **"only idle that goes to NEEDS YOU should be stalled"** — this is already how it works.
  Being stalled is one of the two conditions that put a row in NEEDS YOU, so a stalled row
  is already a summoned row. The rule he proposes is the rule the code implements, which
  means it cannot be the fix.

So the mismatch he sensed is real, but it points the other way from how he phrased it.

## The actual defect

NEEDS YOU is too eager, not too narrow. Concretely, an agent that runs
`sb tell <who> "..." --needs-reply` and ends its turn to wait — doing exactly what the
protocol instructs — is STALLED at zero seconds and summons Andrew. And it does so at the
very moment the reconciler is already about to ping it.

That last point is the one that rests on trusted ground. `DESIGN-TRUTH.md` never mentions
"stalled" or "NEEDS YOU" at all. Its only line on this (`:155-159`, confirmed 2026-08-09)
says that when an agent is idle and neither blocked nor done, **a reconciler pings the agent
itself, not the human** — "that is how we avoid stale idle agents". The code honours this:
`broker.reconcile` iterates exactly the stalled set and pings the agent within ~10s. So the
designated first responder to idle-with-no-excuse is the reconciler. The board summoning
Andrew simultaneously is not something DESIGN-TRUTH asks for; "STALLED means a human should
look" comes only from module docstrings, which are untrusted.

## Why this was not shipped

The fix is a design choice with at least three defensible answers, and picking one is
Andrew's call:

1. **Reconciler-first** — an agent becomes STALLED only after the reconciler has pinged it
   and it stayed idle anyway. Directly matches DESIGN-TRUTH's stated mechanism.
2. **Idle-duration floor** — require N seconds of unexcused idleness before STALLED.
3. **A fourth excuse** — waiting on a reply it asked for via `--needs-reply`.

These are not mutually exclusive; (1) subsumes much of (2).

## Two loose ends found on the way, not fixed

- **A narrow real gap:** if an intermediate agent reports done while a grandchild under it
  still runs (legal), its parent shows STALLED on its row but is dropped from NEEDS YOU by
  the whole-subtree check. Makes the board quieter, not noisier — the opposite of Andrew's
  complaint.
- **A fixture that lies:** `tests/test_richboard.py:305-311` builds a lead-and-idle-child
  shape with `stalled=True` on both, which the real `collect` cannot produce.

## Collision note

`board-awaiting-keypress` is adding a "waiting on a human keypress" state *in place of*
STALLED. That is already one instance of the family of fixes above — narrowing what counts
as STALLED. Any general fix here should land after it, and should be designed knowing it
exists, or the two will fight over the same ranked if/elif chains in `board.marker`,
`board.glyph`, `board.wants_you` and richboard's `needs_kind`/`needs_list`.
