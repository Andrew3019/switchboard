<!--
Notes for whoever edits this file. HTML comments are stripped on the way out, so this is
free; everything outside it is paid for on every spawn bound to this preset. Headings are
stripped and the rest is flattened to ONE line, so nothing may depend on layout or on
being item N of a list.

NO COMMAND IS NAMED HERE, DELIBERATELY. This used to say "run `python3 -m unittest
discover -s tests`" — switchboard's own test command, sitting in a SHIPPED default whose
whole stated purpose is being read and copied into other repos. It is wrong in every repo
but this one, and an agent that runs a command that does not exist has learned that the
check is optional. The instruction is now "find how THIS repo runs its checks and run
them", which is the thing that was always meant and is true everywhere.

This file used to argue that a repo COULD NOT override it, and therefore that naming no
command was forced. That was simply false — preset files layer, and
`.switchboard/presets/verify.md` replaces this one outright. The conclusion survives the
correction on its own merits: a shipped default that names one repo's test command lies to
every other repo, and finding the command is a minute of work an agent is already good at.
A repo that wants its command stated can override this file, or put it in a role prompt or
CLAUDE.md — and now that is a real option rather than a thing the comment denied.

WHAT DID NOT CHANGE, and is the real content: a test that fails without your change is what
separates "I added behaviour" from "I added a test that would pass anyway"; pre-existing
failures get named rather than quietly fixed, because fixing them enlarges the diff nobody
asked for and hides that they were already broken; and "it should work" is the sentence this
preset exists to prevent.

WHAT CHANGED, 2026-08-27, with the workflow repair. This opened "Before you call `sb done`,
prove your work" and read as a stage: run everything, then finish. That is the shape the
adaptive model removed — verification follows the coherent change, in proportion to what the
change can reach, and evidence is bound to a commit rather than re-earned by whoever holds
the work next. So the frame is now EVIDENCE rather than a gate before `done`, with two
sentences added for the two things that were missing: record the commit and environment a
result covers, and do not rerun what already passed on that same commit with the same inputs.
Both matter most to the roles this is bound to — `qa` reads the author's evidence rather than
repeating it — and neither names a command, for the reason above.

The scoping clause on the first bullet ("the ones that can tell your claim true from false")
is doing real work and is not hedging: it is what stops a specialist verifier reading "find
this repo's checks and run them" as "run all of them again".
-->
# verify

Evidence, not confidence. Before you report, know what you actually established.

- Find how this repo runs its checks — its tests, its linter, its build — from the repo
  itself rather than guessing from the language, and run the ones that can tell your claim
  true from false. Widen from there only where what changed could reach further.
- Evidence belongs to a commit and an environment. Record both, with what you ran and what
  came back, so the next agent reads your result instead of paying to re-earn it.
- Do not rerun a check that already passed on the same commit with the same inputs. Rerun
  what the change since could actually have affected.
- If you added behaviour, add the check that fails without it.
- A check that fails for reasons you did not cause is evidence too: name it, say why you
  think it is not yours, and do not fix unrelated things.
- "It should work" is not verification. Never report done on unrun code, and say plainly
  what you could not check.
