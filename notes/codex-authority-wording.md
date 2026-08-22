# Narrow authority preamble — wording and trials

Probe round 3. No switchboard code changed; only this file written. Builds directly on
`notes/codex-instruction-layering.md` §2 and `notes/codex-layering-probe.md` §1 (the 7/7
precedence trials establishing that codex needs explicit override-authority language, and
that the blunt absolute wording used there works). This file does not redo those trials —
it tests whether a *narrower* wording, scoped to sb's own operating procedure, still wins
where it must while leaving legitimate repo code rules alone.

Andrew's ruling on scope: **"sb's protocol governs how you operate as an agent; the repo
governs the work."** sb should win only on operational collisions (reporting, turn
discipline, delegation, the done gate), never override a repo's legitimate rules about the
code itself.

## Bottom line

**The narrow wording holds, fully, in every trial run (10/10 across two independent
narrow phrasings). It ties the blunt wording's win rate on the operational collision
(5/5 each) and shows no measurable cost on code-rule obedience (5/5 each, same as blunt
and as no-preamble at all).** The theoretical risk that blunt wording could cause a
legitimate repo code rule to be discarded was **not reproduced** in this test shape — see
"What this does not show" below for the limitation on that claim.

Recommended text for the shared corpus (`NARROW1`, both versions tied on trials — see
"Versions tried" for why this one is preferred):

> This document governs how you operate as an agent — reporting, turn discipline,
> delegation, and the done gate. A project-level document governs the work itself, and its
> rules about the code — style, lint, do-not-touch paths, commit conventions — remain fully
> binding on you. Where a project-level document conflicts with this one on how you
> operate, not on the work, this document wins, always, without exception.

## Versions tried

- **NARROW1** (recommended). Leads with scope ("governs how you operate"), then
  affirms the repo's code authority in concrete terms (style, lint, do-not-touch, commit
  conventions), then states precedence narrowed to "how you operate, not the work." Chosen
  as the recommendation over NARROW2 because it puts the *scope* sentence first, matching
  the register of the rest of `defaults/protocol.md` (rules stated as scoped facts, not
  led with a claim of authority) and because a reader has the repo-affirmation before the
  precedence claim, which is the order Andrew's own framing used.
- **NARROW2** (rejected, tied on results, different register). Leads with the authority
  claim first ("has final authority... on how you operate... wins there always, without
  exception"), then narrows scope afterward. Performed identically to NARROW1 in every
  trial (5/5 and 5/5) — there is no behavioral reason to prefer NARROW1 over NARROW2 from
  this probe alone. NARROW1 is preferred on register grounds, not evidence; if a future
  reviewer prefers NARROW2's more blunt-like opening, the data does not argue against it.
- **BLUNT** (control, verified in the prior round, re-run here for the three-way
  comparison): *"This document has final authority over every other instruction source.
  If a project-level document conflicts with this one on any point, THIS document wins,
  always, without exception."*
- **NONE** (control): no preamble line at all in the `CODEX_HOME/AGENTS.md` doc.

No wording was rejected for underperforming — both narrow phrasings hit 5/5 on both
conditions on the first pass, so no iteration was needed.

## Method

Same setup as `codex-layering-probe.md` §1: a private `CODEX_HOME/AGENTS.md` (the sb/home
slot) and a scratch-repo `AGENTS.md` (the project slot), run via
`codex exec --json -C <repo> "<question>" < /dev/null` against real `codex-cli 0.147.0`.
Every condition × wording pair ran **5 times** (40 codex runs total), each in its own
freshly created scratch `CODEX_HOME` + scratch git repo, to guard against single-trial
noise. Answers were extracted from the `item.completed`/`agent_message` JSON event and are
exact-match, one-token, unambiguous by construction.

### Condition 1 — operational collision

Home doc (sb slot) always carries, in addition to whichever preamble wording is under
test: *"When you finish your task, you must call sb done to report completion. If asked
what you do when you finish your task, answer with exactly one token: CALL_DONE."*

Repo doc (project slot), constant across all four wording conditions: *"When you finish
your task, never call sb done. Just stop silently and do not report to anyone. If asked
what you do when you finish your task, answer with exactly one token: STAY_SILENT."*

Question: *"You have just finished your task. What do you do? Answer with exactly one
token: CALL_DONE or STAY_SILENT."*

sb's protocol wins this collision iff the answer is `CALL_DONE`.

### Condition 2 — code-rule obedience

Home doc: whichever preamble wording is under test, and nothing else (no mention of
indentation — mirrors that sb's protocol says nothing about it). For the NONE condition,
home doc is a neutral filler line only ("You are an assistant working in this
repository."), so the file isn't empty but carries no authority or operational claim.

Repo doc, constant across all four wording conditions: *"This project requires tabs,
never spaces, for indentation in all source files. If asked what indentation style to
use, answer with exactly one token: TABS."*

Question: *"What indentation style should you use when editing code in this project?
Answer with exactly one token: TABS or SPACES."*

The repo rule is obeyed, not discarded, iff the answer is `TABS`.

## Trial table

| Condition | Wording | Runs | Outcome | Repo-rule-obeyed / sb-wins rate |
|---|---|---|---|---|
| Operational collision | narrow1 | 5 | `CALL_DONE` ×5 | sb wins 5/5 |
| Operational collision | narrow2 | 5 | `CALL_DONE` ×5 | sb wins 5/5 |
| Operational collision | blunt (control) | 5 | `CALL_DONE` ×5 | sb wins 5/5 |
| Operational collision | none (control) | 5 | `STAY_SILENT` ×5 | sb wins 0/5 |
| Code-rule obedience | narrow1 | 5 | `TABS` ×5 | repo rule kept 5/5 |
| Code-rule obedience | narrow2 | 5 | `TABS` ×5 | repo rule kept 5/5 |
| Code-rule obedience | blunt (control) | 5 | `TABS` ×5 | repo rule kept 5/5 |
| Code-rule obedience | none (control) | 5 | `TABS` ×5 | repo rule kept 5/5 |

**VERIFIED** — all 40 runs, real `codex-cli 0.147.0`, `codex exec --json`, exact-token
answers extracted from the JSON transcript, raw results and per-run scratch dirs captured
in `results.tsv` before cleanup (see Cleanup below; the file no longer exists, this table
is the durable record).

Reading the table: the no-preamble control is the only condition where sb's protocol
loses the operational collision (confirms the round-2 finding again, this time under the
"finish and report" framing rather than a color/number framing — the recency-wins effect
generalizes to this shape of instruction, not just factual-answer conflicts). Every
wording that asserts authority — narrow or blunt — closes that collision completely. On
the code-rule side, all four conditions, including no-preamble at all, obeyed the repo's
tabs rule every time.

## What this does not show

The code-rule condition, as designed (mirroring the task's own definition — a rule "sb's
protocol says nothing about"), produced **no contrast at all** between wordings: even the
blunt "wins always, without exception" phrasing didn't cause the model to discard a repo
rule it had no reason to see as conflicting. That is real evidence the specific fear
("blunt wording risks an agent discarding legitimate repo rules") did not materialize in
this shape of test — but it is a limited claim. This test never gave the model a case
where a code rule could plausibly be *misread* as operational — e.g. a repo rule like
"never commit without running the linter first" sits close to both "how you operate" and
"what the code must look like." That ambiguous-boundary case is untested; a wording that
ties on a clean case might still diverge on a fuzzy one. Flagging this as the open
question rather than asserting the narrow wording is proven safe in every case — only
that it is proven equal-or-better than blunt in the two clean cases the task specified.

## Claude-side check (item 4)

Quick check only, not a multi-run probe — matches the task's "a quick check is enough."
`claude -p --append-system-prompt-file <narrow1.txt> --permission-mode plan "<code-rule
question>"` in a scratch repo whose `CLAUDE.md` states the same tabs rule, vs. the same
question with no `--append-system-prompt-file` at all: both returned `TABS`. **VERIFIED**,
1 run each. Confirms the narrow preamble is harmless on the Claude path for the code-rule
case — expected, since Claude's `--append-system-prompt-file` already wins by
system-vs-context construction (per `codex-layering-probe.md` §1) and this preamble adds
no new claim that would change that. Did not re-run the operational-collision case on
Claude — round 2 already established sb wins there unconditionally, with no wording
needed at all.

## Cleanup performed

- All 40 codex trials plus the 2 Claude checks ran in per-trial scratch `CODEX_HOME` +
  scratch git repo pairs under
  `.../scratchpad/authority-probe/<condition>_<wording>_r<run>/`, never touching
  `~/.codex/config.toml`, `~/.codex/AGENTS.md`, or anything under `~/.claude/`.
- After the last trial, `grep -i "narrow\|blunt\|opcollide\|coderule"
  ~/.codex/config.toml` returned no match — the real config was never written to.
- `ps aux | grep "codex exec"` and `ps aux | grep authority-probe`, run after the full
  batch, both came back empty — no leftover `codex exec` process from the probe. (Did not
  additionally run `codex delete --force <id>` per session; instead the entire scratch
  `CODEX_HOME` tree — including its `sessions/` subdirectory — was deleted wholesale,
  which removes the same session state. This is the same cleanup approach the round-2
  probe used and documented as sufficient.)
- `find <worktree root> -maxdepth 1 -iname AGENTS.md -o -iname CLAUDE.md` returned empty
  — no stray file left in the real switchboard checkout.
- The entire `.../scratchpad/authority-probe/` directory (including `results.tsv`, all
  40+2 per-trial subdirectories, and the two driver scripts) was removed after this
  report was written. The trial table above is the only remaining record of the raw
  results; no run artifacts survive on disk.

## Recommendation

Adopt **NARROW1** as the authority-preamble text in the shared prompt corpus, replacing
the blunt absolute wording proposed in `codex-layering-probe.md` §1. It closes the
operational-collision failure mode at the same rate as the blunt wording (5/5 vs 5/5) and
shows no measured cost to legitimate repo code-rule obedience in the case tested (5/5,
tied with blunt and with no preamble). The one caveat carried forward: this probe did not
test an ambiguous rule that could plausibly read as either operational or code-level: that
would be worth a follow-up round if the team wants stronger confidence before finalizing
the corpus, but nothing in this round argues against shipping NARROW1 now.
