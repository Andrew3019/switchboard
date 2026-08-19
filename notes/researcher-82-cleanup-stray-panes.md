# Scout: root cause of stray panes after `sb cleanup`

## Code path (CLI → herdr close)

- `sb cleanup` → `switchboard/cli.py:451`/`1119` → `Broker.cleanup()`, `switchboard/broker.py:3994`.
- Per candidate agent, `cleanup()` closes **two** panes, not one:
  1. The agent's own pane: `broker.py:4326` resolves the real target via
     `_close_target(a)` (`broker.py:5268`), then `broker.py:4350-4356` calls
     `self.h.release_agent(target, ...)` then `self.h.close_pane(target)`
     (herdr calls: `pane release-agent`, `pane close` — `switchboard/herdr.py:1060`,
     `:422`). Wrapped in `try/except HerdrError` (`broker.py:4357-4383`): a
     `pane_not_found` is treated as already-closed (logged `cleanup_pane_gone`);
     any other `HerdrError` **refuses the whole row** (unless `--force`) and the
     row's `pane_id` stays set, so the next sweep retries it. This half is
     failure-safe by design.
  2. The **board pane** opened beside every agent (`_open_board`,
     `broker.py:1351`) is closed separately by `_close_board(a["name"])`
     (`broker.py:4387`, method at `broker.py:1419-1483`), called *after* the
     agent's own pane is already marked `done` (`broker.py:4393`).

## Root cause: `_close_board` silently orphans its pane on any failure

`_close_board` (`broker.py:1419-1483`) is the one piece of this whole flow that
is **not** failure-safe, and it says so about itself:

- It looks up the tracked pane in `meta` (`board_pane:<name>`), resolves it
  through the same `_close_target` identity check used for agents, then:
  - if `_close_target` refuses (identity mismatch, or **herdr could not be
    asked at all** — `_close_target` returns `(None, "herdr could not be
    asked whose pane that is")` whenever `_agent_states()` is `None`,
    `broker.py:5318-5319`) → logs `board_close_refused` and **still deletes
    the `meta` row** (`broker.py:1468-1473`).
  - if `self.h.close_pane(target)` itself raises *any* exception (timeout,
    herdr error, anything) → logs `board_close_failed` and **still deletes
    the `meta` row** right after, unconditionally (`broker.py:1474-1483`).
  - Only the plain success path actually results in a closed pane. Every
    other path — refusal or exception — leaves the physical pane exactly as
    it was, but throws away the only record (`meta:board_pane:<name>`) that
    switchboard ever had of it existing.

This is explicit, reasoned design in the docstring (`broker.py:1419-1456`):
"Never raises. A close that half-happened is worse than a board left
behind" and "A refusal leaves the pane alone and still drops the meta row:
... keeping it would have the next `_open_board` ... believe a board is
up." The tradeoff was made deliberately, but the consequence is: **any
transient herdr hiccup at the exact moment `_close_board` runs (herdr
unreachable for that single cached probe, a `pane close` call timing out,
a stray HerdrError of any kind) permanently orphans that pane.** Nothing
will ever retry it — not the next `sb cleanup`, not `_open_board` (which
would just believe no board is tracked and split a *new* one), not
`sb restore`. This matches "sometimes it happens, sometimes it doesn't"
exactly: it depends on whether one specific `close_pane` call, made once,
happens to succeed.

Contrast with the agent's own pane close (finding above): that path is
wrapped so a failure **holds the row open and is retried**. The board
close has no such retry path — by the time it runs, the parent agent row
is often already about to be marked `done` (board close happens right
before `store.set_state(..., "done")` at `broker.py:4387` vs `:4393`), so
even if the whole `cleanup()` call is re-run later, there is no longer any
tracked row to trigger `_close_board` again for that name.

## Contributing factor: one stale herdr snapshot for the whole sweep

`_close_target` resolves pane identity off `_pane_cache`, filled from a
single `herdr agent list` call cached once per `sb` process
(`_agent_states()`/`_fill_agent_caches`, `broker.py:5202-5231`, explicitly
documented as "one probe per `sb` process"). A bulk `sb cleanup` sweeping
many agents closes many panes (agent + board, per candidate) against that
one up-front snapshot, issuing the agent-pane close and the board-pane
close back to back with no settle time. This doesn't break the *agent*
side (it fails closed and retries), but it means the entire sweep's
identity resolution — including every board close — is racing herdr's own
live bookkeeping for however long the sweep runs, using an answer that can
already be stale by the time the last few candidates in a big sweep are
reached. This is circumstantial (I did not reproduce a live race), but it
is the natural amplifier for the `_close_board` failure mode above: the
more agents in one sweep, the more `close_pane` calls fired against a
single-shot herdr view, the more chances for one board-close call to hit a
transient herdr hiccup — each one of which is now unrecoverable.

## Ruled out (already fixed, tested)

The obvious naive bug — closing an agent's pane but never touching the
board pane beside it, leaving one empty tab per agent — is exactly what
`_close_board` exists to prevent, and it is pinned by
`ClosingTakesTheBoardWithItTest` in `tests/test_workspace.py:771-809`
(`test_closing_an_agent_closes_its_board`, `test_the_closed_board_is_forgotten`,
`test_a_board_already_gone_is_tolerated`). The happy path is solid. I did
not find any test exercising `_close_board`'s failure/refusal paths
(`board_close_refused`, `board_close_failed`) — grepped `tests/*.py` for
`_close_board`/`board_pane:` and only the happy-path tests above turned up.

## Is the fix clear, or does it need a design call?

Leaning **needs a human design call**, not "just retry it":

- The forgetful behavior on refusal/failure is not an oversight — it's an
  explicit tradeoff already argued in the docstring, made to avoid a worse
  failure mode (a stale tracked pane causing `_open_board` to wrongly
  believe a board already exists, or a `restore` under the same name
  reusing a stranger's pane). Any fix has to preserve that reasoning for
  the case it was written for (confirmed identity mismatch — someone else
  now holds that pane, or the pane is legitimately gone) while NOT applying
  it to the case that actually causes the leak (herdr couldn't be reached /
  `close_pane` raised for a reason that says nothing about whether the pane
  is still there, e.g. a timeout).
- A plausible localized shape: only forget the `meta` row when
  `_close_target` gives a *reason that proves the pane isn't ours to close*
  (identity mismatch, confirmed gone), and leave it (or log something a
  future sweep can act on) when the failure is "herdr could not be asked"
  or an exception from `close_pane` itself — i.e. treat those like the
  agent-pane-close path already does (refuse-and-retry) rather than
  swallow-and-forget. That's a small, mechanical change to
  `_close_board` (`broker.py:1419-1483`), but it's a real policy change to
  a function whose current behavior is intentional and documented, so I'd
  want a human to confirm the intended failure semantics before touching
  it rather than assume "retry" is obviously right.
