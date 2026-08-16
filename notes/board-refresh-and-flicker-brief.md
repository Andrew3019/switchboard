# board-refresh-and-flicker — task as given

Verbatim from Andrew:

> also can we make the board update faster? seem to be every 2 seconds right now. make it
> every .5 seconds. and there are some state changes with idle and stuff causing it to show
> in NEEDS YOU for like one frame (frame is 2 seconds). can we find a way to dedup this.
> maybe just only show if it persists more than 1 frame

Two changes, related: the refresh interval, and the one-frame NEEDS YOU flicker. The
"only show if it persists more than 1 frame" is his suggestion, not a requirement — note
that at 0.5s a frame is a quarter of what it was, so a persistence rule counted in frames
means something different than it did at 2s. Judge whether it should be time-based instead.
