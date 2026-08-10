# DESIGN-TRUTH audit — consolidated

Six groups, 51 entries, read-only. Per-group evidence with file:line:
/tmp/sb-audit-1-placement.md, -2-messaging.md, -3-lifecycle.md, -4-human.md,
-5-roles.md, -6-removals.md

Totals: 11 SATISFIED · 31 PARTIAL · 22 BROKEN · 0 UNVERIFIED
(counts are per checkable claim, so they exceed the 51 entries)

Verified personally by the reconciler (worker-2), not just reported:
- broker.py:2902 `self._push_state(a, IDLE, why)` — blocking pushes the agent to IDLE.
  Two groups independently probed that a sibling's ordinary mail then clears the block.
- board.py:331 `_visible_len` counts characters after stripping ANSI, with no account of
  double-width glyphs — so one emoji or CJK char makes a row wrap and every row below is
  off by one. This is the click bug, not the side panel.
