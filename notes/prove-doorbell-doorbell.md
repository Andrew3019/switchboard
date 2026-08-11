# prove-doorbell — where the detail is

Full report, with timestamps, commands and teardown: `audit/doorbell-on-main.md`.

One line: the acceptance check-2 failure on merged `main` is real, not a coverage miss —
a parent held inside a 150 s tool call still had its child's report rung at it directly,
because herdr reports every pane `idle`/`done` and `Broker._busy` believes it, so *when
idle* never defers.

Raw logs (session scratchpad, not committed):
`scratchpad/runs/accept-sbcqnj9r/run.log` (the acceptance run),
`scratchpad/probe-busy.log` + `scratchpad/probe.py` (the forced-busy probe).
