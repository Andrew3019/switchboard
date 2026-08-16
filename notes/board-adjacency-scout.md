# Scout: can a board pane know which agent shares its own tmux tab?

Read-only. No files touched besides this note. Verified against running code and,
where noted, live `herdr` output from the actual fleet (not a stale doc).

## 1. Can a board pane discover its own location?

**Yes — but not via tmux, and not via the earlier scout's framing.** Re-verified
`grep -rn "tmux" --include="*.py" .`: the only hit is a comment in `stats.py:436`.
Zero tmux python module usage, zero `TMUX`/`TMUX_PANE` reads anywhere in the repo.
Confirmed live: this session isn't even running inside real tmux (`$TMUX` is
empty here), and the running `switchboard.board` processes on this machine
(checked via `ps -wwE`) have no `TMUX`/`TMUX_PANE` in their environment either —
whatever multiplexer herdr drives, it isn't raw tmux with the standard env vars.

What IS there, and better: **`HERDR_PANE_ID`, `HERDR_TAB_ID`, `HERDR_WORKSPACE_ID`,
`HERDR_ENV`**. Confirmed live on a running board process's own env
(`ps -wwE -p <pid>`): `HERDR_PANE_ID=w1JP:p2 HERDR_TAB_ID=w1JP:t1
HERDR_WORKSPACE_ID=w1JP`. And on my own agent pane right now (`echo
$HERDR_PANE_ID` etc.): `HERDR_PANE_ID=w1JY:p5`, `HERDR_TAB_ID=w1JY:t4`. herdr
injects these into every pane it opens (`board.py`'s launch line is a bare `exec
… -m switchboard.board` with no argv/env of its own — the env vars are already
sitting there from herdr, inherited through the `exec`).

Switchboard already leans on this exact mechanism elsewhere: `broker.whoami()`
(`broker.py:681`) reads `HERDR_PANE_ID` to answer "who is calling", and
`broker.py:2986` reads `HERDR_WORKSPACE_ID`. So self-location isn't a hole to dig
— `HERDR_TAB_ID` is the same door, just not walked through yet in `board.py`.

## 2. Can it map from tab to the neighbouring agent?

**Partly — one half exists in herdr, the other half is missing from what the
board is allowed to read.**

- **herdr side: yes.** `herdr pane list` returns `tab_id` on every pane (verified
  live, real output):
  ```
  {"pane_id":"w1JY:p5","tab_id":"w1JY:t4","agent":"claude","agent_status":"working",...}
  {"pane_id":"w1JY:p6","tab_id":"w1JY:t4", ...}                    <- no "agent" key = the board pane
  ```
  That `p5`/`p6` pair is literally this task's own tab — my agent pane and its
  board sibling, caught live. So pane→tab, and its inverse tab→panes, is a real,
  already-available herdr query. No herdr change needed for this half.

- **switchboard side: missing.** `herdr pane list` only carries the generic
  `agent` kind ("claude"), never the switchboard-level agent *name* ("researcher-78").
  That mapping (`pane_id` → name) lives only in the store's `agents.pane_id`
  column (`store.py:198`, used by `whoami()`). And `board.py` is explicitly
  forbidden from touching the store — its own docstring says so, and
  `tests/test_panel.py::RendererImports` enforces it — because a board import
  once caused schema rebuilds and false `failed` states. The board only ever
  reads `status.AgentStatus` rows published by the collector through
  `panel.read()`. I checked that dataclass (`status.py:405-458`) field by field:
  **no `pane_id` field exists on it at all.** The collector already has
  `agents.pane_id` in hand when building each row (`status.py:1201` builds
  `AgentStatus(...)` from the same query that has `row["pane_id"]` available) but
  never puts it on the published object.

  So today there is no legal path from "board knows its own `HERDR_TAB_ID`" to
  "board knows the neighbouring agent's name" — the join key is dropped exactly
  where the board is architecturally cut off from the store.

## Is `tab -> agent | board` a real invariant?

Confirmed in code and confirmed live, but it's a **usage convention switchboard
enforces, not something herdr's data model guarantees.**

- Code: `board.open_beside()` (`board.py:1060`) is the only thing that ever opens
  a board pane, and it always splits the calling agent's own `pane_id` — same
  tab, by construction (`split_pane`'s docstring: one split per tab). It's called
  from every `broker.delegate` and every `sb start`
  (`board.py:36-39`), and `DESIGN-TRUTH.md:567` confirms it as design intent:
  "Every sb-made view is split with the board" — no opt-out.
- Live data (`herdr pane list`, this run): every 2-pane tab I found had exactly
  one `agent`-bound pane and one unbound sibling — consistent with agent+board.
  But **not every tab has this shape**: several tabs in the live list are
  single-pane with no agent at all (`w1GX:t1`, `w1GX:t7`, `w1HW:t2`, `w1JD:t2`) —
  plain shells, or a workspace root before an agent was ever spawned into it.
  herdr has no concept of "board pane" — nothing stops a human from closing just
  the board half of a pair (leaving a lone agent pane) or opening a manual third
  pane in the tab. So the pairing is real for every pane switchboard itself
  opens, but a board reading tab_id must handle "0 agent siblings" and
  "more than 2 panes in the tab" as real, not theoretical, cases.

## Verdict

**Buildable, but not fully there today — one missing piece, and it's entirely on
the switchboard side, not herdr's.**

Path: self-locate via `HERDR_TAB_ID` (already injected, already used elsewhere in
the codebase) → call `herdr pane list` to get the tab's other pane_id(s) (already
exposed, verified live) → look up the sibling pane_id in the published agent
snapshot to get its switchboard name.

The last hop is the gap: `status.AgentStatus` needs a `pane_id` field, populated
in `status.py`'s `collect()` from data the collector already queries
(`row["pane_id"]`), and threaded through `panel.py`'s serialize/deserialize round
trip (`agent_from_dict`/`snapshot_from_dict`, `panel.py:319-345` — there's a
round-trip test tied to this that would need updating too, per the comment at
`panel.py:312`). That's a small, contained switchboard change — no herdr
codebase change needed, since herdr already exposes everything path required
except the name-level join, which was always switchboard's own job.

Worth flagging for whoever implements it: calling `herdr pane list` is a
subprocess call, and the board already redraws twice a second
(`REFRESH`/`board_refresh` setting) — the earlier board-layout scout
(`notes/board-layout-scout.md`) already called out subprocess cost as a real
concern for per-refresh work. A tab's own pane membership doesn't change often,
so this wants caching/throttling rather than a `pane list` call on every tick —
a design decision for the implementer, not a blocker to buildability.
