# dead-parent-live-children — task as given

Context: `board-ghost-sessions` triage reported, as a side observation, that a dead parent
stays on the board while any of its children are still alive — real and separately observed,
with the design doc silent on whether it is wanted. That was put to Andrew as his call.

His answer, verbatim:

> yes but this should almost never happen

So: the display behaviour stays as it is — a dead parent with live children is still drawn.
The open work is that the situation itself should be rare, and it apparently is not.
