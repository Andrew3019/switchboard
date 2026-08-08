# wf protocol

You are an agent in a `wf` workflow. Coordinate ONLY through these commands (`wf` is on PATH).
Do not try to contact other agents any other way.

- `wf inbox` — read your unread messages. Run this when told you have mail.
- `wf tell <who> "<msg>"` — send a message. `<who>` is `parent` or an agent name.
- `wf done "<summary>"` — you have finished. Give a ONE-LINE summary. Always call this last.

Your name, role, and parent are given in your system prompt.
Keep summaries to one line. Do not paste file contents into messages — pass file paths instead.

## If you are an orchestrator

- `wf delegate "<task>" --role <role> [--name <n>] [--model cheap]` — spawn a child agent.
  It runs independently. You do NOT wait; end your turn. You will be poked when it finishes.
- `wf status` — list agents.

Delegate real work rather than doing it yourself. When all your children have reported and
the round is complete, call `wf done "<summary>"`.

## Failure rule

If `wf delegate` fails, DO NOT do the work yourself. Report it:
`wf done "blocked: delegate failed - <error>"`. Doing a child's work yourself defeats the
whole point and hides the failure.
