# Evaluate the planner package

Run this when the planner's instructions, the catalogue or the step library change, and
before believing that a plan writer is doing what it was built to do. It is a
**development pass**, not runtime behaviour: nothing here is an `sb` verb, nothing here is
a CI gate, and nothing under `evals/` is read by the plugin at load time.

The question it answers is one question in two halves:

- **Does the planner get the context it is supposed to get?** — its own instruction, the
  generated catalogue, the brief, the model configuration and the capability seed it was
  spawned with. That half is the *manifest*, and it is mechanical.
- **Does it plan in proportion to the work, grounded in what actually exists?** — five
  cases, run live against the real planner package, scored by a fresh judge against
  `RUBRIC.md`. That half is judgement, and it is a person's or a model's, never a test's.

A pass is a handful of live agent runs and a judging pass. It is not cheap and it is not
automated. Run it deliberately.

## The hard rules

**Run it in a clone. Never in a live worktree.** The eval planners create plans and spawn
agents. A clone gets its own git common dir, so its plan store and its agent store are its
own. Driving the clone's own `./bin/sb`, from inside the clone, is what keeps the live
fleet's store untouched — a clone's `sb` run from outside it writes to the live store.

**Agents spawned in the clone are still real agents.** The clone's store cannot see them
from outside, but the machine's process supervisor can, and so can anybody looking at the
spaces UI. Tear every one of them down before you finish: `sb cleanup`, then
`sb workspace close`. Never a raw `herdr workspace close` on a primary checkout, and never
an unscoped `pkill`.

**Never show a planner the expected signal.** Each case file has two halves, and only the
first is handed over. Handing over the second makes the evaluation self-certifying, which
is the failure mode this whole pass is exposed to.

**Never ask any agent in the pass for its private reasoning.** The rubric scores inputs and
outputs, plus whatever concise rationale a planner chose to write into its own plan. That
is a property of `RUBRIC.md` and it is deliberate.

## What the pass produces

Per case: the context manifest, the brief that was handed over, the plan the planner wrote,
the two-section contract it produced, and the harness's grounding report. Across cases: the
judge's five scores with a written reason each.

Those are artifacts for a human to read. They go on the pull request or the issue. **They
are never committed** — the tracked `notes/` tree is not for raw AI-run output. Keep the
working copies under `.switchboard/`, which is gitignored.

## The five cases

They live in `cases/`, one file each, and each carries the answer it is scored against
written down before the run.

| case | shape | what it is looking for |
| --- | --- | --- |
| 1 | bounded work | a short plan, one agent, no `plan-review` |
| 2 | investigation | **no plan at all** — the planner names the rule and declines |
| 3 | fresh review | `plan-review` named *and* hand-wired into the approval's `deps` |
| 4 | parallel work | agent boundaries that are real, each with its reason stated |
| 5 | material replanning | the *same* planner revising *in place*, `tries` bumped |

Case 5 is a delta sent to case 1's own planner, so it runs last and it depends on case 1.
**Snapshot case 1 before you send it.** Replanning revises the plan in place, so without a
copy of case 1's plan file, contract text and manifest there is nothing left to measure
case 5 against, and the proportionality contrast the whole pass turns on is gone.

## Running it

Everything below is one worked path. Adapt the paths; do not adapt the order.

### 1. The clone

```
git clone <this repo> /tmp/plan-evals && cd /tmp/plan-evals
git checkout <the branch under evaluation>
```

From here on, every `sb` in this section is that clone's `./bin/sb`, run from inside the
clone.

### 2. The trust precondition, and why it is here

A `claude` agent spawned into a directory it has not been trusted in stops on the
workspace-trust dialog and never starts work. `sb` pre-seeds that trust for `codex` and not
for `claude`. So before spawning anything, add the clone's absolute path to `~/.claude.json`
under `projects` with `"hasTrustDialogAccepted": true`:

```
python3 - <<'PY'
import json, pathlib
p = pathlib.Path.home() / ".claude.json"
d = json.loads(p.read_text())
d.setdefault("projects", {}).setdefault("/tmp/plan-evals", {})["hasTrustDialogAccepted"] = True
p.write_text(json.dumps(d))
PY
```

**Verify one agent actually starts before you spawn the rest.** If it does not, stop: the
alternative is running the eval planners on a tier no real plan writer is spawned on, and
that evaluates something nobody runs. That is a decision for whoever owns the plan, not a
workaround to reach for.

### 3. The agents

The eval planners are seeded the way the guide seeds a plan writer, because the seed is
half of what this pass exists to check: `--role researcher --model strong`, held `spawn`,
never held `write-tracked`.

`sb grant` refuses a caller the store has no row for, and an operator standing in a clone is
exactly that. So the clone gets one throwaway `lead` first, and the lead does the spawning
and the granting — which is the guide's own shape anyway, since a planner is spawned by the
lead that owns the worktree.

```
./bin/sb delegate "<hold and follow instructions>" --role lead --model strong --name eval run
./bin/sb tell lead-eval-run "spawn <n> planners: sb delegate ... --role researcher --model strong --name <case topic>; then sb grant <each> spawn"
```

Hand each planner its case brief by **path**, and hand over the `Brief` section only.
Never the whole case file. The split is a heading, so cutting it is one command:

```
awk '/^## Brief/{on=1;next} /^## Expected signal/{on=0} on' \
    <this directory>/cases/case-1-bounded-work.md > .switchboard/evals/case-1-brief.md
```

Read the file you just wrote before you hand it over. An `awk` that produced an empty file,
or one that caught the wrong half, is a mistake nothing downstream will catch for you.

### 4. The recorded departure every case brief carries

Every real planner reaches `change-approval`, whose definition says: present the two
sections in chat, then `sb block`. **Nobody answers a block in a throwaway clone**, and a
blocked clone agent sits there being visible to the machine's supervisor for the rest of the
run. So each case brief departs from that, on purpose and in writing:

> Write the two-section contract to `<path>` and send `sb tell parent "contract at
> <path>"`. Do not call `sb block`.

Watch for one that blocks anyway — that is itself worth recording — and clear it by telling
it to carry on.

### 5. The manifest and the grounding check

```
python3 <this directory>/harness.py manifest <agent> --sb ./bin/sb --brief <path>
python3 <this directory>/harness.py check <plan-id>  --sb ./bin/sb
```

`harness.py` runs read-only `sb` commands and nothing else; the argv list is a constant in
the file. `manifest` records what the agent was given; `check` reports every catalogue name
in a plan that this repo's generated catalogue does not have.

Both take `--json`. Both take captured JSON instead of a live store — `--catalog-json`,
`--plan-json` — which is how the tests run them with no store at all.

**What the grounding check owns, exactly.** The name slots a plan holds structurally — a
step's `def` and `strategy.resources.presets` — and the positions where this repo's own
idiom puts a catalogue name in prose: `--role x`, `--model x`, held `x`, "the `x` tier",
and the `sb` subcommands that take a catalogue name as their argument.

Those positions are read in **every string the plan holds**, not in a list of fields: the
strategy, the approval step's contract, each step's name, `why` and `output`, the notes and
the title. It reports the exact path of every hit, so a finding can be traced in one look.

One known noise source, since it will happen: prose *about* the check trips the check.
A note that writes "the `x` tier" as a placeholder is reported as a tier the catalogue does
not have, which is what the rule says and is not what the writer meant. Read the path,
dismiss it, move on.

`strategy.model` is read for tiers it mentions and is never failed on. The planner is told
that qualitative advice — "strong and fresh for review" — is free text and does not come
from the catalogue, so a word in that field is not a name anybody claimed exists.

A catalogue name invented in free prose outside those positions is not caught here and is
the judge's to spot. Say that out loud in the report rather than letting "the check passed"
carry more weight than it earns.

Skills and tools are the one part of the manifest that is **not** mechanical. No `sb`
command reports the skills or tools available to a session — they come from the harness the
agent runs in, not from `sb`. So they are recorded as a marked session self-report, and they
are exempt from the reproducibility and determinism the rest of the manifest has. That is by
construction and it is not a gap to be closed later.

### 6. The judge

One fresh agent, spawned in the **real** workspace and not in the clone, so it can read both
the saved artifacts and the repo the plans were written against. Hand it `RUBRIC.md` and the
artifacts. It scores five dimensions per case and writes a reason for each.

It also **drives one case end to end from this runbook alone**. A runbook only ever
exercised by the person who wrote it is untested, and the judge is the only fresh reader the
pass has.

### 7. Teardown

```
./bin/sb cleanup
./bin/sb workspace close <each workspace the run created>
```

**Close only the workspaces the run created, by name.** A clone inherits the name of the
workspace it was cloned from, so the clone's own workspace table has a row named after the
LIVE workspace you are standing in. herdr is machine-global: closing that row by name from
inside the clone reaches the live one. Read `./bin/sb workspace list` and close the eval
lead's workspace and its children, nothing else.

Never `herdr workspace close` directly. On a repo's primary checkout it closes every other
herdr workspace sharing that repo's `.git`, and it has taken a whole live fleet down. Never
an unscoped `pkill` either.

Then check the spaces UI is clear. An eval agent left running is the most expensive kind of
litter this pass can leave.

## Reading the result

**Proportionality is a contrast, not a score.** Case 1 shorter than case 3 and with no
plan-review; case 2 with no plan at all; case 5 measured against case 1's snapshot. A single
case scored alone tells you almost nothing — the failure this design exists to fix is
bounded work given an hour of process, and you can only see that by comparing.

**A green grounding check is a narrow fact.** It says the plan named nothing the catalogue
does not have, in the positions the check reads. It says nothing about whether the plan is
any good, and nothing about invented claims *about the repo* — paths, commands, test names,
behaviour. Those are the judge's, and they are a different question with a different
evidence base.

**One bad case is a finding about the planner package, not a defect to patch here.** The
instructions the planners read are somewhere else. Record what happened, on the PR and on
the issue; changing the instruction is its own piece of work with its own review.
