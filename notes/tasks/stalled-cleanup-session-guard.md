# Task: don't sweep a row that `sb restore` cannot bring back

Small and tight. One condition, one test, one live confirmation. **Do not redesign anything
else on this branch.**

## Why

Branch `stalled-agent-cleanup` changes `sb cleanup` so a bare sweep also closes a row whose
turn edge switchboard gave up on (`_forget_turn` fired, `agents.turn` still NULL, a live
`_busy` re-check agrees). See `Broker.cleanup`'s `given_up_on` and its docstring.

When I specified that bar I claimed such a row must have a session id by construction —
it had run hooks, so it had run `sb`. **That is false, and it was verified false.**
`hooks._agent_row` resolves the caller by session id *and then by `HERDR_PANE_ID`*
(hooks.py:181-200), precisely because the store only learns a session id on the agent's
first `sb` call. So turn edges are written for agents that have never run `sb`.

Verified live: a real agent that never ran an `sb` command reached `session_id=None`,
`turn=None`, with a `turn_forgotten` in the log; a bare sweep closed it, and
`sb restore` then refused — *"has no session id; nothing to restore"*. `Broker.cleanup`'s
own docstring promises "closing costs only the pane" for every row it takes, and for that
row it is not true.

Full evidence: `notes/qa-6-stalled-cleanup-verification.md`, section "Finding: …is FALSE".

## The fix — decided

`given_up_on` refuses a row with **no session id**. A row `sb restore` cannot bring back is
not one an unattended sweep should take, and this is the class with the weakest evidence
behind the verdict anyway. `--force` stays the escape, as everywhere else on this gate.

Make the refusal say something true about *why* — a caller looking at a row the board has
given up on, being refused anyway, should learn that it is unrestorable and that `--force`
still closes it. Keep it short and match the voice of the refusals already there.

The other option — teaching `restore` to work from the pane id — is **out of scope**. If
you think it is the better answer, say so in your report; do not build it.

## Constraints

- Change only what this needs. `_revive`, the `sb done` delivery block, `herdr.py`'s
  delivery path, `broker.py`'s `_spawn` block / `_took_a_turn`, and `status.py`'s grace
  constants all belong to other work — do not touch them.
- `DESIGN-TRUTH.md` is the only trusted document and **only Andrew edits it**. Every other
  doc and code comment, including the docstrings on this branch, is untrusted until you
  check it against the code. If a docstring or `cli.py`/`protocol.md` line on this branch
  now overstates what a sweep takes, fix that line too — it is part of this change.
- Shared checkout: no `git stash`, never leave files staged, re-read a file before editing.

## Proving it

- **One test** pinning it, and check it **fails** against `HEAD` before your change — a
  test that passes either way pins nothing. Never teach the fake herdr new tricks; if that
  is what it would take, skip the test and write the sentence saying what is unproven.
- Suite green: `/Users/andrew/anaconda3/bin/python -m pytest tests` (the pythons on PATH
  look broken when they are not). It is 1240 now.
- **One live confirmation** in an isolated `git clone` driven by **that clone's own
  `./bin/sb`** — never run a clone's `sb` from outside it. Reproduce the shape qa-6 did (a
  real agent that never runs `sb`, a stuck turn edge, the real repair path, then a sweep)
  and show the sweep now refuses it and `--force` still closes it. Shortening
  `turn_stale_grace`/`turn_doubt_grace` via a copied `defaults/` and `SWITCHBOARD_DEFAULTS`
  is how qa-6 made this tractable; do the same.
- Tear down everything you create — herdr is machine-global, so your agents appear in
  Andrew's spaces UI. Kill only by verified pid after checking each process's cwd with
  `lsof -d cwd`. **Never an unscoped `pkill`.** Leave the live fleet's collector alone.

## Landing

Commit on `stalled-agent-cleanup`, on top of what is there. **Do not push, no PR, do not
merge, do not touch `main`** — I am integrating, and `main` is moving under us.

Report with `sb done`: the condition as you expressed it, what the test pins, what the live
run showed, and anything unproven.
