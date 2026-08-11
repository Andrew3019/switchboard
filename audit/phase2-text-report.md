# Phase 2 — the human-facing text cluster (item D and item 2.6)

Branch `p2-text`, commits `48364f9` and `888126a`. Full suite green: 1806 passed.

## What each message says now, and why the old one was wrong

**1. Undelivered mail, in `sb status` and in `sb inspect`** (`status.py`, `_attention` and
`render_detail`). Both said, for every agent, that the doorbell is held while an agent is
mid-turn and released when it goes idle. For a blocked agent that is false twice over: its
mail is held on `_is_blocked` in `_ring` and `flush_pending`, and only the human's own
`tell` lifts that; and since `block()` stopped reporting herdr state, going idle is not a
state a blocked agent passes through at all. Both places now branch. A blocked agent is
told its mail is held until the human answers the block, not until it goes idle, and that
answering releases it. The wording for every other agent is unchanged.

**2. The blocked row in NEEDS YOU** (`status.py`). It ended `→ sb tell <name> "..."`,
flat. Only the human's `tell` clears a block — `Broker.tell` passes
`answer=(me == HUMAN)`, and anyone else's message is written and then held. It now reads
`→ the human answers it: sb tell <name> "..."`, so it no longer reads as an errand another
agent can run. This one is not in the scope report; it is the same wrong mechanism a few
lines away, so I fixed it rather than leaving a fresh contradiction next to the fix.

**3. `sb status` presented as Andrew's own surface** (item 2.6). DESIGN-TRUTH.md:
"`sb status` is not for Andrew — only `sb board` is." Four places now point at the board:

- `cli.py`, `sb inbox` as the human — "a blocked agent waits on `sb board` as a marked row
  with its reason".
- `cli.py`, `sb block`'s confirmation to the blocking agent — "your reason marks your row
  on the human's board until they answer". Deliberately *not* `sb board`: that verb is
  hidden from `sb --help`, refused to anything with an agent row, and never named to an
  agent in the shipped prompts, which say "a board row".
- `cli.py`, `--mine`'s help — was "(for a human: every agent)", which read as an invitation
  to use `sb status` as their view. Now says a human has no subtree and the board is
  theirs.
- `defaults/settings.toml`, the `[vocabulary]` note on why there is no `blocked_prefix` —
  a fifth place, not in the scope report's four, saying a block "reaches you through
  `sb status --needs-me`".

`--needs-me`'s help also gained "stalled", which `needs_human` filters on and the help did
not name.

## Proved rather than assumed

In a `git clone` of the repo into a scratch directory, checked out on this branch, driving
that clone's own `./bin/sb` (the store lives under the clone's `.git`, so it is isolated;
agents named `w1`/`w2`, which no live-fleet agent uses):

- Both undelivered branches render as intended in real `sb status` and `sb inspect` output
  — the blocked agent gets the human-answer wording, the unblocked one beside it still
  gets "released when it goes idle".
- The new `sb inbox`, `sb block` and `sb status --help` text, as printed by the real CLI.
- The mechanism the text describes: another agent's `tell` to a blocked agent logged
  `ring_held {"reason": "blocked"}` and left the block standing; the human's `tell` cleared
  the block and fired the doorbell (`agent prompt` failed only because the seeded pane is
  not a real one).

Tests: three in `tests/test_status.py`, one in `tests/test_inspect.py`. One existing
assertion in `tests/test_broker.py` pinned the old `sb inbox` text and now pins `sb board`.

## Left unproven, and left alone

- No automated test covers a genuinely blocked agent in a real pane. The held-then-released
  path is proved by the live clone run above, not by the suite.
- `broker.py:3104` — the refusal when an agent tells the human — still names
  `sb status --needs-me` as where the human looks. Same class as 2.6, but it sits in the
  mail machinery another agent owns this phase, so I left it.
- The scope report warns that rewording 2.6 without first adding a NEEDS YOU list to the
  board would strip Andrew's blocked-agent visibility. That is wrong: `board.wants_you`
  already marks a blocked row with an arrow and colour and `board.note` already prints
  `BLOCKED — <why>`. No `board.py` change was needed and none was made.
- `BUILD-PLAN.md` still lists 2.6 as outstanding. Left uncorrected on purpose — two other
  agents are in this phase and a three-way edit of that file is a merge cost for no gain.
- Untouched, not this cluster: 2.4, 2.5, C, 2.2/B, 2.3, A.
- One stray desktop notification fired on the machine during the clone's `sb block` test:
  `notification show` reaches the real herdr even from an isolated clone.
