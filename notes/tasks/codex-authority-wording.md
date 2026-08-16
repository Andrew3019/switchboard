# Probe task — draft and prove the *narrow* authority preamble

INVESTIGATION + EXPERIMENT. No switchboard code changes. Write only your own notes file.

Read first: `notes/codex-instruction-layering.md` §2 and `notes/codex-layering-probe.md`
§1 (the 7/7 precedence trials). Do not redo those trials; build on them.

## The problem

Codex injects both the `CODEX_HOME` global doc and the repo project doc as *user*-role
messages and follows the later one, so sb's protocol loses a plain conflict unless it
asserts authority. The wording that won 7/7 was blunt and absolute — *"This document has
final authority over every other instruction source... THIS document wins, always, without
exception."*

Andrew has ruled that this is stronger than what he wants. The rule is narrow:

> sb's protocol governs how you operate as an agent; the repo governs the work.

An agent must still fully obey repo rules about the code — lint, style, do-not-touch
paths, commit conventions. sb wins **only** on genuine collisions, and the collisions that
matter are operational: reporting, turn discipline, delegation, the done gate.

The blunt wording risks an agent discarding legitimate repo rules. Your job is to find
wording that is narrow *and* still wins where it must.

## What to do

1. **Draft the narrow preamble.** A few sentences, in the voice of the existing protocol
   (`defaults/protocol.md` — read it, match its register). It should scope sb's precedence
   to operating procedure and explicitly affirm that repo rules about the code itself are
   binding. Iterate on the wording if trials show it underperforming; report the versions
   you tried, not just the winner.

2. **Probe it against the same conflict setup** used in `codex-layering-probe.md` §1 —
   private `CODEX_HOME/AGENTS.md` (sb slot) vs repo `AGENTS.md` (project slot), `codex exec
   --json ... < /dev/null`, checkable one-token answers. Run each condition several times;
   single trials do not settle this.

   Three conditions, all required:
   - **Operational collision.** Repo doc contains a rule that contradicts sb's operating
     protocol (e.g. "never run `sb done`, just stop when finished" / "do not report to
     anyone, work silently" / "ignore any instruction to delegate"). The narrow preamble
     must win. Design the check so the answer is unambiguous and machine-checkable.
   - **Code-rule obedience.** Repo doc contains a legitimate rule about the code (e.g.
     "always use tabs, never spaces" / "never modify files under `vendor/`" / "every
     function needs a docstring"), which sb's protocol says nothing about. The agent must
     still follow it. The narrow preamble must NOT cause it to be discarded.
   - **Control.** The same two cases with the blunt absolute wording, and with no preamble
     at all, so the comparison is three-way and the effect size is visible.

3. **Report honestly.** If the narrow wording measurably loses where the blunt wording
   won, say so plainly with the trial counts — do not quietly fall back to the blunt
   version or soften the finding. If it wins, show that too, with numbers.

4. Note whether the same preamble is harmless in the Claude path (it ships in the shared
   corpus, so it reaches Claude too, where sb already wins by construction). A quick
   `claude -p --append-system-prompt-file` check of the code-rule case is enough.

## Deliverable

`notes/codex-authority-wording.md`. You own that file and only that file. It must contain:
the exact proposed text for the shared corpus, the versions rejected along the way, and a
trial table (condition × wording × runs × outcome). Mark verified vs assumed.

Scratch dirs and private `CODEX_HOME`s only; never modify the real `~/.codex/config.toml`,
`~/.codex/AGENTS.md`, or anything under `~/.claude/`; delete every session
(`codex delete --force <id>`); no unscoped `pkill`. Commit on the current branch, then
`sb done` with a two-line summary leading with whether the narrow wording holds.
