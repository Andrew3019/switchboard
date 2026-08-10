# A spawn reported success for an agent that never got its task — what the confirmation proved, and what it proves now

Work by agent `fix-spawn-falsepos` on branch `fix-spawn-falsepos` (forked from `phase-1`
at `1ff9285`). Everything below was run in throwaway `git clone`s per
`audit/isolated-instance.md`; the live fleet's store was never written to, nothing was
installed, pushed or merged, and `main`, `DESIGN-TRUTH.md` and `BUILD-PLAN.md` are
untouched.

## 1. What the old confirmation actually proved

`Herdr.deliver` sent the task with `agent prompt` and then asked `_took_prompt` whether
the agent had moved:

```python
if a.change_seq > seq or (a.state == WORKING and not was_working):
    return True
```

`state_change_seq` is herdr's own counter, stamped on an agent whenever **herdr's reading
of that agent's status changes**. So the test proved one thing only: *herdr's status
record for this name changed at some point after we sent the text*. It never looked at the
text, and nothing in it distinguishes a turn from any other reason a status might move.

## 2. Why a task could still be lost

Measured, not inferred. In a fresh checkout, `herdr agent start` returns with the pane
already `interactive_ready` while Claude Code is still showing its **workspace trust
dialog**:

```
 Accessing workspace:
 /Users/andrew/.herdr/worktrees/sbfsp2/fsp-e1
 Quick safety check: Is this a project you created or one you trust? …
```

`agent prompt` types the task into that modal and presses Enter. The text is discarded and
the Enter answers the dialog. Answering it changes the agent's status — and that is the
"movement" the confirmation was waiting for. Captured at the moment the old code returned
`True`:

| agent | pane when prompted | status seen | verdict | outcome |
|---|---|---|---|---|
| `fsp-e1` | trust dialog | `blocked`, seq 2508→2512, after 0.53 s | delivered | never ran |
| `fsp-e3` | trust dialog | `done`, seq 2510→2515, after 0.71 s | delivered | never ran |
| `fsp-e4` | trust dialog | `blocked`, seq 2511→2516, after 0.02 s | delivered | never ran |
| `fsp-e2` | trust dialog | no change for 20 s | not delivered → re-sent | ran |

Not one of those three transitions is a turn. `sb delegate` returned all four names to the
caller. This is the same signature the third acceptance run recorded for `pa3-w1` and
`pa3-mainchild` (`audit/phase1-acceptance-3.md` §2) — zero context, `$0.00`, herdr
`done` — and both of those were also the first spawns into a brand-new clone.

The trust dialog is remembered per checkout parent (`~/.herdr/worktrees/<clone>`), which
is why the loss clusters on the first fan-out into a new one and disappears afterwards.
It is the trigger, not the disease: **any** startup state that eats a prompt while moving
the status passes the old test.

Two smaller faults in the same function, both fixed here:

- The baseline was snapshotted **once**, before the first attempt. By a third send, up to
  a minute later, any change since — including the answer to the dialog that ate the first
  send — counted as confirmation.
- Related, and worth knowing on its own: **the first prompt after `agent start` is lost
  far more often than not, even with no dialog involved.** In two warm fan-outs, 10 of 10
  spawns needed the re-send. Delivery has therefore always rested entirely on the
  confirmation being truthful, which is why a confirmation that lies loses agents outright.

## 3. What changed

`sb delegate` now confirms delivery against **the child's own transcript**, not against
anything herdr says. Claude Code appends submitted text to
`~/.claude/projects/<slug of cwd>/<session>.jsonl`, verbatim, about a second after it goes
in — measured at 0.8–1.0 s, and verbatim for a 1682-character single-line task. A prompt a
dialog swallowed leaves no record at all, because it never happened.

- `output.task_arrived(cwd, text, since=…)` — new. Matches by content rather than session
  id, because a spawn that never took its prompt never starts a session, and skips files
  untouched since the send so it stays cheap enough to poll twice a second.
- `store.transcript_dir(cwd)` — new, split out of `transcript_path`, which needs a session
  id this question is asked before there is one.
- `Herdr.deliver(..., proof=…)` / `_took_prompt` — `proof` is the only thing believed when
  it is available. The status read behind it survives only as a fallback for an agent
  whose own record cannot be found, and now insists on `working`: every false positive
  observed was a transition to `blocked`, `done` or `idle`, and none of those is a turn.
- The baseline is re-read before every attempt.
- Unchanged, and still the loud half: after `retries.deliver_attempts` sends with no proof,
  the spawn raises `TaskUndelivered`, the row is recorded `failed` rather than `working`,
  and the caller is told the name is not working and to respawn it.

## 4. Evidence

Ground truth for "it got the task" is the pane and the store together: a lost agent sits
at `0% 1M │ $0.00` having taken no turn, and never reports.

**Before (unfixed, `1ff9285`) — 26 spawns, 9 lost, all 9 reported as successful.**

| clone | spawns | lost |
|---|---|---|
| `sbfsp`, first fan-out into a new clone (`fsp-a1`…`a6`) | 6 | **6** |
| `sbfsp`, three later fan-outs (`fsp-b`, `fsp-c`, `fsp-d`) | 16 | 0 |
| `sbfsp2`, first fan-out into a new clone (`fsp-e1`…`e4`) | 4 | **3** |

Cold subtotal: 9 lost of 10. Warm subtotal: 0 of 16.

**After (`f0fa70c`) — 18 spawns, 0 lost.**

| clone | spawns | lost | note |
|---|---|---|---|
| `sbfix1` (`fsp-g1`…`g4`) | 4 | 0 | no dialog; confirmed in ~1.0 s, no re-send |
| `sbcold1`, new clone (`fsp-h1`…`h4`) | 4 | 0 | ~27 s each — one re-send apiece |
| `sbcold2`, new clone (`fsp-i1`…`i4`) | 4 | 0 | ~27 s each |
| `sbcold3`, new clone (`fsp-j1`…`j6`) | 6 | 0 | all six hit the trust dialog |

`sbcold3` is the direct replacement of the failing case — six spawns, every one prompted
while the trust dialog was up, every first send correctly refused after 20 s, every
re-send confirmed within 1.1 s, every agent ran and reported:

```
fsp-j1 +3.8 pane=TRUST-DIALOG | +3.8 prompt | +23.9 confirmed=False
       | +27.4 pane=no dialog | +27.4 prompt | +28.4 confirmed=True | delegate returns
```

Suite: `/Users/andrew/anaconda3/bin/python -m pytest tests -q` → **1781 passed**
(1764 before, +17 new).

## 5. What it costs

A spawn whose first send is eaten now waits out `timeouts.deliver_ms` (20 s) before the
send that works, so a cold fan-out is ~27 s per agent instead of ~5 s. That 5 s was the
bug: it was the time it took to be told a lie. When the first send does land, the proof
confirms in about a second, so nothing that was already working got slower.

## 6. What I did not test

- The loud-failure path live: no spawn in this run needed a third attempt, so
  `TaskUndelivered` was exercised only by its unit tests.
- Any agent kind but `claude`. The proof is Claude Code's transcript; another kind would
  fall through to the `working` fallback, which is weaker.
- `sb restore`, which passes `--resume` and delivers no task, so it never enters this path.
- Whether a task can be lost for a reason *other* than a startup dialog. The proof does not
  care why — it only ever answers whether the text is in the agent's record — but the
  trust dialog is the only cause I saw.

## 7. Noticed, not fixed

- **The first prompt after `agent start` is usually lost even with no dialog** (§2). Worth
  someone deciding whether `agent start` should be followed by a readiness wait rather than
  a doomed send and a 20 s timeout — it would take ~20 s off every cold spawn.
- `sb status` reports these agents as `working … << STALLED` with `herdr says idle — turn
  ended, sb done never called`, which is accurate but arrives minutes later and only to
  someone reading the tree. With this fix the row should no longer appear for this cause.
- Everything in `audit/phase1-acceptance-3.md` §6 (the done-agent ring loop, the
  `--dry-run` silence) is untouched here and belongs to whoever owns the collector.
