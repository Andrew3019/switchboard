# Why blocking cost the agent its name, and what makes it survivable

Branch `fix-block-oneway`, on top of `fix-sb-path` (`ae9e095`). Nothing installed, pushed
or merged; `main`, the installed symlink, `DESIGN-TRUTH.md` and `BUILD-PLAN.md` untouched.

Picks up `audit/phase1-acceptance-2.md` §5.2, which confirmed the failure end to end but
not its cause, and `audit/phase1-scope.md` item 1.6, which concluded the root cause "lives
in herdr … switchboard can only detect-and-surface". **That conclusion is wrong, and this
is the correction: the cause is a call switchboard makes.**

---

## 1. The causal step

`herdr pane report-agent` does not annotate a pane's agent. It **replaces** it. The named
agent that `herdr agent start <name>` registered is evicted and a source-reported record
put in its place, and a reported record is not an addressable target.

The two shapes are visible in `agent list`:

```
{"agent": "claude",   "name": "fix-doorbell-cwd", ...}   ← named   → agent get: OK
{"agent": "worker-2",                             ...}   ← reported → agent get: agent_not_found
```

`Agent.from_json` falls back `name or agent`, so switchboard still *sees* the second row —
which is exactly why `_binding_lost` can tell it apart from a dead agent — but herdr will
not act on the name any more.

**Measured on herdr 0.8.0, against a throwaway pane created for the purpose:**

| step | `herdr agent get bindprobe-b` |
|---|---|
| `herdr agent start bindprobe-b --kind claude --pane <p>` | OK — `agent=claude name=bindprobe-b` |
| `herdr pane report-agent-session <p> --source switchboard --agent bindprobe-b …` | OK — still bound |
| `herdr agent prompt <p> "…"` (pane-targeted) | OK |
| **`herdr pane report-agent <p> --source switchboard --agent bindprobe-b --state idle --seq 2`** | **`agent_not_found`** |

So it is **not** "herdr saw the agent leave the foreground because `sb` ran in the pane",
which is what `Herdr.prompt_pane`'s docstring said and what everything downstream believed.
Every `sb` command runs in the pane and costs nothing; `report-agent-session` costs nothing;
one `report-agent` costs the name.

And **the state value is irrelevant**. `block` deliberately pushed `idle` rather than
`blocked`, on the reading that herdr's `blocked` badge is what un-targets an agent. The
badge does un-target it — and so does `idle`, and so does every other value. The state is
not what evicts the name. Making the call is.

## 2. There is no way back

All three candidates tried on the evicted pane, agent still alive in it:

- `herdr pane release-agent <p> --source switchboard --agent <n> --seq N` — deletes the
  reported record instead of handing detection back. The pane then drops out of
  `agent list` **entirely**, and `agent explain <p>` answers `agent_not_found`. Re-checked
  at 12/24/36/48 s: it does not come back. This is strictly worse than doing nothing.
- `herdr agent start <n> --kind claude --pane <p>` — `agent_pane_busy`, "not an available
  shell". The agent is running in it, so the pane can never be re-registered.
- `sb restore <n>` — **refuses**, and would not have helped anyway. The evicted agent is
  still in `agent list`, so `_alive` says it is running and `restore` raises "already
  running — nothing to restore. To reach it: … sb tell", which is the one thing that
  cannot reach it. (This answers the open question in `phase1-acceptance-2.md` §5.3.
  Pinned by `test_restore_is_not_a_way_back_from_a_lost_name_binding`.)

Prevention is the only fix that exists.

## 3. What was changed

Two calls, both removed. Nothing else.

- **`Broker.block`** no longer calls `_push_state(a, IDLE, why)`. Blocked-ness has always
  lived in our store — `_is_blocked`, `sb status --needs-me`, the board all read it there —
  and herdr's own detector reads a waiting agent as `idle`/`done` unprompted, which is the
  very value the report was buying at the price of the name.
- **`Broker._unblock_if_needed`** no longer calls `report_state(…, WORKING)`. This was the
  second half of the failure and the sharper one: it ran *one line before the doorbell*, on
  the belief that a report re-registers the name. It evicted the name in the same breath as
  the ring that needed it — which is precisely the observed signature in
  `phase1-acceptance-2.md` §5.2, `unblocked` immediately followed by
  `ring_failed … "reason": "name_binding_lost"`, block cleared and answer undelivered.

`Broker.done` is now the only `report_state` caller left in the codebase — see §5.

Docstrings that asserted the old causal story (`Herdr.report_state`, `Herdr.prompt_pane`,
`Broker._ring`, `Broker._binding_lost`, `Broker._is_blocked`) now carry the measured one.
Phase 1's detection (`_binding_lost`, the `unreachable` note on `sb tell`, `sb interrupt`'s
refusal) is untouched and still correct — it is now a backstop rather than the whole answer.

## 4. Proof

**Unit.** `tests/test_broker.py` gains `EvictingHerdr`, a fake that charges the real price:
`report_state` puts the name into `unreachable`, so any code that reports state on a live
agent loses the doorbell. Under it,
`test_the_humans_answer_reaches_a_blocked_agent_on_an_evicting_herdr` blocks an agent, has
`HUMAN` answer with `sb tell`, and asserts the ring landed, the message is delivered, the
block cleared, and `unreachable()` is None. It fails on the pre-fix code, twice over.
Two existing tests that asserted the old pushes (`…does_not_push_herdrs_blocked_state`,
`…unblocks_it_first`) now assert that **no** state is pushed.

Full suite: **1750 passed**.

**Live, in an isolated `git clone`** (own store, driven by the clone's own `./bin/sb`, per
`audit/isolated-instance.md`; the tester's session has no row in that store so `sb` resolves
it as `HUMAN`, which makes the answer the real human path):

```
sb start '… run sb block "which colour?" …' --name bo-probe
  → sb status: bo-probe  blocked   << BLOCKED ;  NEEDS YOU: blocked: which colour?
  → herdr agent get bo-probe: OK   {"agent":"claude", "name":"bo-probe"}      ← was agent_not_found

sb tell bo-probe 'HUMAN ANSWER: blue. …'
  → "sent to bo-probe"                        (no UNREACHABLE note)
  → events: unblocked bo-probe
            agent prompt bo-probe "You have mail. Run: sb inbox"  rc=0
  → messages: delivered_at set, read_at set   (the agent read it)
  → sb status: bo-probe  done   ✓ heard blue
```

**The control, on the same agent and the same pane, a minute later.** `sb done` is the one
remaining `report_state` caller, so it should still evict — and it does, which is what shows
the removed call was the cause rather than something else about the run:

```
after sb done →  herdr agent get bo-probe: agent_not_found
                 agent list row: {"agent": "bo-probe"}      ← the reported shape, no name
```

Teardown: `sb cleanup bo-probe --force`, clone deleted, `herdr workspace list` back to the
live fleet only. Two throwaway probe workspaces (`bindprobe`, `bindprobe2`) closed. No
unscoped `pkill` was used; nothing on the live fleet was written to.

## 5. Two things found on the way, deliberately NOT changed

Both are decisions, not defects I was asked to fix.

1. **`sb done` still evicts the name.** Same one call, same permanent effect, but on an
   agent that has just declared itself finished — and `_finished_and_unreachable` already
   treats that agent as unringable, so today nothing contradicts it. It does mean
   DESIGN-TRUTH's "`sb done` keeps the agent open … the orchestrator then decides" is only
   half true: the orchestrator can close it or read it, but can never `sb tell` it again.
   Whether that matters depends on whether the `--message` summary that report carries into
   herdr's own UI is worth the name. That is Andrew's call.
2. **A block answered by typing into the pane never clears.** DESIGN-TRUTH:253-259 names
   that as the answer path ("answering by typing into the pane is what works"), and it does
   still deliver — pane input never went through the name registry. But nothing then clears
   the store's `blocked` row: `set_state` only stamps `ended_at` for `done`/`failed`, so
   `_revive` never fires, and the agent stays on `sb status --needs-me` and keeps every
   sibling's mail held under `ring_held` forever. The `sb tell` path clears it correctly.
   The obvious fix — a blocked agent running any `sb` command is a blocked agent that is
   running again, so clear it, exactly as `_revive` argues for a finished row — is a
   behaviour change with its own design question, and is not what I was asked for.
