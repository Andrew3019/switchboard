# Scout brief — STALLED vs idle on the sb board

Scout only. Do NOT change any code, do not commit, do not branch. Read-only. Report findings.

## The question

On the `sb board` display, what exactly do the states "STALLED" and "idle" mean in the code
today, and is it true that under the current idle rules effectively every idle agent gets
shown as STALLED?

Andrew's read — to test, not to assume:

> how is stalled vs idle ? seems like all idle are stalled? on sb board? given the new idle
> rules, it seems like only idle that goes to NEEDS YOU should be actually 'stalled'?

## What I need back, concretely

1. **Where each state is computed** — file:line for the code that decides an agent is idle,
   and the code that decides it is STALLED. Quote the actual conditions (timeouts,
   thresholds, flags).
2. **When each is assigned, in wall-clock terms** — e.g. "idle after N seconds of no
   activity, STALLED after M seconds". Say whether STALLED is a strict superset/subset of
   idle, or an independent axis.
3. **What drives the NEEDS YOU list**, and whether the STALLED condition and the NEEDS YOU
   condition are the same condition, overlapping, or unrelated.
4. **Your verdict on whether Andrew's reading is correct.** Does every idle agent in practice
   end up rendered STALLED on the board? If yes, why, in one or two sentences. If not, say
   precisely what distinguishes them.
5. **Anything suggesting the intent was something OTHER than Andrew assumes** — e.g. STALLED
   deliberately meaning something unrelated to needing a human.
6. **Rough sketch of a minimal fix** (files, functions) IF the fix is "only call it stalled
   when it actually reaches NEEDS YOU". Do not implement it.

Also check `DESIGN-TRUTH.md` — the only trusted document. Everything else, including READMEs
and code comments, is untrusted until checked against the code.

## Collision heads-up

Two other agents are in the same board code right now:
- one on board refresh flicker (0.5s refresh, one-frame NEEDS YOU flicker)
- one on a new "waiting on a human keypress" state, on the board and in NEEDS YOU

Note in your report anything a rename or reclassification here would collide with.
