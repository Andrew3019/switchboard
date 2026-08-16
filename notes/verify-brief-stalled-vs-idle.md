# Adversarial verification brief — STALLED vs idle

Read-only. No edits, no commits, no branches. Your job is to try to REFUTE another agent's
findings, not to agree with them.

Another agent produced `notes/stalled-scout2-stalled-vs-idle.md`. Read it. Its conclusion is
that Andrew's complaint dissolves: it claims STALLED was deliberately designed to mean
"idle with nothing excusing it, so a human should look", and that every STALLED row already
qualifies for the board's NEEDS YOU section. That conclusion, if right, means we do NOT ship
the fix Andrew imagined. So it needs to be right.

Verify these independently, from the code itself. Do not take the other report's line
numbers or quotes on trust — open the files and check.

## Claims to test

1. **`stalled` is `idle` minus exactly three excuses, computed on the same tick, with no
   separate stall timeout delaying it behind `idle`.** Is that actually true? Look for any
   grace period, debounce, or threshold that makes STALLED lag idle. If one exists, the
   other report is wrong on its central point.

2. **Every agent marked STALLED on a board row also appears in the board's NEEDS YOU
   section**, except for the one claimed gap (a lead whose *grandchild* is still busy —
   excluded from NEEDS YOU by a whole-subtree check, but still showing the STALLED marker on
   its row because the stalled flag itself only looks one generation down). Test both halves:
   is the claimed gap real, and are there OTHER ways to be STALLED without being in NEEDS
   YOU that the other report missed?

3. **The reverse direction:** how often, in practice, is an agent idle but NOT stalled? The
   other report says the three excuses are narrow and most ordinary agents match none of
   them. If that is right, then on a typical board nearly every idle row reads STALLED —
   which is exactly what Andrew observed. Confirm or refute.

4. **What the board actually renders.** Separate from the internal booleans: for an agent
   that is idle-but-excused, what does its row visibly say, versus a stalled one? Is there a
   visible distinction at all, or do they look the same to a human scanning the board? This
   is the question Andrew was actually asking, and the other report answers it only
   indirectly.

5. **Intent.** The other report leans on `DESIGN-TRUTH.md` and module docstrings to argue
   STALLED was always meant to be "a human should look". `DESIGN-TRUTH.md` is the only
   trusted document — everything else, including docstrings and comments, is untrusted until
   checked against code. Say what DESIGN-TRUTH actually states about these states, quoting
   it, and whether the code matches.

## Deliverable

A short report at `notes/verify-stalled-vs-idle.md` plus a summary. For each of the five
points: CONFIRMED, REFUTED, or PARTLY, with the file:line evidence you personally checked.
End with your own one-paragraph verdict on the question that matters: **is Andrew's
complaint pointing at a real defect we should fix, or at a design that is already correct?**
