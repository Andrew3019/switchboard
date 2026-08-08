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

THE REST IS UNCHANGED and is the real content: a test that fails without your change is
what separates "I added behaviour" from "I added a test that would pass anyway";
pre-existing failures get named in the summary rather than quietly fixed, because fixing
them enlarges the diff nobody asked for and hides that they were already broken; and "it
should work" is the sentence this preset exists to prevent.
-->
# verify

Before you call `sb done`, prove your work.

- Find how this repo runs its checks — its tests, its linter, its build — and run them.
  Look for how the repo itself does it rather than guessing from the language.
- If you added behaviour, add a test that fails without your change.
- If checks fail for reasons you did not cause, say so explicitly in your summary rather
  than fixing unrelated things.

"It should work" is not verification. Never report done on unrun code.
