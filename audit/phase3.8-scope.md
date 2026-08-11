# 3.8 — enforce that an agent reports before its turn ends: read-only pass

Written before any code changed. What the code says today, what the CLI actually does
(run, not read), and the pass/fail tests the build is held to.

## What exists

- `sb done` (`broker.py:3358`) sets `state='done'`, `sb block` (`broker.py:3425`) sets
  `state='blocked'`. Both write an event. Nothing calls them but the agent's own goodwill.
- `herdr.start_agent` (`herdr.py:405`) builds `agent_args` — `--permission-mode`, model
  flags, `--resume`, one joined `--append-system-prompt` — and hands them to
  `herdr agent start … -- <args>`. No `--settings` anywhere in the tree (`grep`: zero hits).
- Identity: `Broker.whoami` resolves `CLAUDE_CODE_SESSION_ID` → `agents.session_id`, else
  `HERDR_PANE_ID` → `agents.pane_id`. The session id is claimed lazily, on the agent's
  first `sb` call (`_claim_session`), so **an agent that has never run `sb` has no
  `session_id` in the store** — which is exactly the agent this hook exists to catch. The
  pane-id fallback is therefore load-bearing here, not a nicety.
- `store_dir()` is `<shared .git>/agentflow/` — shared by every worktree of the repo.

## What the real CLI does (verified by running it, 2026-08-11)

`claude -p "…" --settings <file>` with a `Stop` hook, no `--bare`:

- The hook **fired**. `HOOKS.md`'s correction is right: `--settings` merges into that
  session only, and `--bare` would skip hooks entirely.
- Payload on stdin (recorded verbatim in the probe log):
  `{"session_id":…, "transcript_path":…, "cwd":…, "prompt_id":…, "permission_mode":…,
    "hook_event_name":"Stop", "stop_hook_active":false, "last_assistant_message":"HELLO", …}`
- Printing `{"decision":"block","reason":"…"}` on stdout with exit 0 blocked the stop and
  gave the model another turn, in which it complied.
- On that second turn the payload carried **`stop_hook_active: true`**. That flag is the
  loop cap: the gate never blocks twice in one stop-chain.
- A crashing or non-zero hook is non-blocking, so every failure path fails open.

## The rule the gate applies

Resolve the caller from `session_id`, else `HERDR_PANE_ID`. Then, in order:

| Condition | Verdict | Why |
|---|---|---|
| `stop_hook_active` is true | allow | already nudged once this stop-chain; the cap |
| caller resolves to no agent row | allow | not one of ours, or not yet registered — never deadlock a session we cannot name |
| `state` in done / blocked / failed | allow | it reported |
| `awaiting_task = 1` | allow | spawned with a placeholder and given nothing; it was told to wait, so this turn legitimately ends without a report |
| agent has a live child (`working`/`blocked`, `ended_at IS NULL`) | allow | the protocol tells a delegating parent to end its turn and wait for the poke; blocking that would push it to report done over work still running |
| otherwise | **block** | "call `sb done` or `sb block`" |

Every allow that is not the trivial "it reported" writes an event, so the escapes are
visible on the board rather than silent.

## Loop risk and how it terminates

A hook that blocks a turn prompts a turn that could block again. Two independent stops:

1. `stop_hook_active` — verified true on the re-entry turn — means at most **one** block
   per stop-chain. A non-compliant agent is nudged once, then released; 3.5's reconciler
   is what catches it after that. The hook prevents the common case; it does not fight.
2. Compliance ends it earlier: `sb done`/`sb block` moves the state and the next stop
   passes on the first check.

The block reason says the nudge happens only once, so an agent that genuinely has nothing
to report does not spiral trying to satisfy it.

## Turns that legitimately end without a report

Three, all handled above: the placeholder turn before a task arrives, a parent waiting on
children, and any session that is not a registered agent. One case is deliberately NOT
exempt: an agent that already reported, is then spoken to in its pane, and answers — it is
`working` again (`_revive`), so it is nudged once to report again. That is the protocol
being applied, not a false positive.

## Pass/fail tests

Live, in an isolated clone (primary evidence):

- **P1** an agent given a task it finishes without calling `sb done` is stopped, and the
  text it is given names `sb done` / `sb block`.
- **P2** an agent that does call `sb done` stops on the first try, unobstructed.
- **F1** the gate must never block twice in a row (proved by the same run: P1's agent ends
  after the single nudge whatever it does).

Automated (two or three, no more, and no new tricks in the fake herdr):

- **T1** the gate blocks a `working` agent and allows a `done` one.
- **T2** `stop_hook_active` allows unconditionally — the loop cap.
- **T3** every spawn carries `--settings <file>`, and the file it names holds a `Stop`
  hook. (Pins the wiring; the delivery itself is P1/P2's job.)

Out of scope, stated so it is not mistaken for an omission: `broker.py`'s
tell/interrupt/ask cluster and the collector are owned by other agents right now and are
not touched. The wiring goes in `herdr.start_agent`, which is the one place every spawn
and every restore passes through — a hook that must not be skippable cannot depend on
each call site remembering to ask for it.
