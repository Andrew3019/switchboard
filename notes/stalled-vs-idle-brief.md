# stalled-vs-idle — task as given

Verbatim from Andrew:

> how is stalled vs idle ? seems like all idle are stalled? on sb board? given the new idle
> rules, it seems like only idle that goes to NEEDSS YOU should be actually 'stalled'?
> invsetigate this, if this is clearly the case and the intent seems correct, go and dispatch
> a fix for this automatically end to end. no need to involve me

He has delegated the decision: investigate first, and only proceed to a fix if the finding
is clear AND the intent reads as correct. If it is not clear, or the intent turns out to be
something else, report instead of shipping — "no need to involve me" is permission to act on
a clear answer, not permission to guess.

Related work in flight, same code: `board-refresh-flicker` (0.5s refresh + one-frame NEEDS YOU
flicker) and `board-awaiting-keypress` (a new "waiting on a human keypress" state on the board
and in NEEDS YOU).
