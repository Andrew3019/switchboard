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

**Do not restore that planner, and do not replace it.** A planner finishes when it hands
the shape back, so case 1's is `done` by the time case 5 exists — and `done` is not closed:
the pane stays, the name still answers, and `sb tell <the case-1 planner>` is how the delta
reaches it, with its own reasoning still in context. `sb restore` is for an agent `cleanup`
took away, which here is the teardown and runs after case 5, so a restore attempted now is
refused (`already running — nothing to restore`) and nothing is wrong. Putting a FRESH
planner on the delta is case 1 again, not replanning — the case is unrunnable without that
same agent, and its own file says what else to hand back to it before you send.

## Running it

Everything below is one worked path. Adapt the paths; do not adapt the order.

### 1. The clone

Clone the **worktree you are standing in**, not the git common dir: a worktree clone lands
already on the branch, which makes the checkout a no-op rather than a guess.

```
git clone "$(git rev-parse --show-toplevel)" /tmp/plan-evals && cd /tmp/plan-evals
git checkout <the branch under evaluation>       # a no-op if you cloned a worktree
mkdir -p .switchboard/evals                      # nothing else creates it, and step 3 writes here
```

From here on, every `sb` in this section is that clone's `./bin/sb`, run from inside the
clone.

**The clone's catalogue is not this checkout's catalogue.** Repo-local config under
`.switchboard/` is gitignored, so a role, preset or tier defined there does not clone — one
recorded pass had seven roles live and six in the clone. Read
`./bin/sb plugin plans catalog` in the clone and compare before you believe a grounding
report: checking a plan against a *larger* vocabulary than its planner saw is exactly how an
invented name passes.

### 2. The trust precondition, and why it is here

A `claude` agent spawned into a directory it has not been trusted in stops on the
workspace-trust dialog and never starts work. `sb` pre-seeds that trust for `codex` and not
for `claude`. So before spawning anything, add the clone's absolute path to `~/.claude.json`
under `projects` with `"hasTrustDialogAccepted": true`:

Back it up first and keep the write short. That file is a live global config every running
Claude session writes to, so a read-modify-write can clobber somebody else's write; and
dumping it without `indent` collapses a pretty-printed config to one line.

```
cp ~/.claude.json ~/.claude.json.evals-backup
python3 -c 'import json,pathlib;p=pathlib.Path.home()/".claude.json";d=json.loads(p.read_text());d.setdefault("projects",{}).setdefault("/tmp/plan-evals",{})["hasTrustDialogAccepted"]=True;p.write_text(json.dumps(d,indent=2))'
```

**Verify one agent actually starts before you spawn the rest.** If it does not, stop: the
alternative is running the eval planners on a tier no real plan writer is spawned on, and
that evaluates something nobody runs. That is a decision for whoever owns the plan, not a
workaround to reach for.

**Whether this step is load-bearing is not settled, and that is worth knowing before you
debug it.** Agents do not run in the clone directory: they run in a herdr worktree at
`/root/.herdr/worktrees/<clone-basename>/<workspace>`, a path this step never touches. In
two recorded passes claude agents started fine with only the clone path trusted. Do it
anyway — it costs a line — and if one does hang on the dialog, trust the worktree path too.

### 3. The agents

The eval planners are seeded the way the guide seeds a plan writer, because the seed is
half of what this pass exists to check: `--role planner`, whose shipped template is strong,
holds `spawn` and never holds `write-tracked`.

An operator standing in a clone has no agent row, so the clone gets one throwaway `lead`
first and that lead does the spawning — the guide's own shape, since a planner is spawned
by the task owner that holds the worktree.

```
./bin/sb delegate "<hold and follow instructions>" --role lead --model strong --name "eval run 0825"
./bin/sb tell lead-eval-run-0825 "spawn <n> planners with ./bin/sb delegate, --role planner, one --name per case"
```

**Quote every `--name`.** It takes one argument, and `--name eval run` is refused outright
with `unrecognized arguments: run`.

**Never reuse a topic from a previous pass.** `sb` allocates the name against the clone's
own store, which is empty, while herdr enforces names machine-wide — so a second pass is
refused with `agent_name_taken` pointing at a worktree you thought was gone. Date-stamp the
topic, or read `herdr agent list` first.

**Poll `./bin/sb status --all` to learn a planner has finished; there is no other route.** A
human has no inbox, `sb board` refuses outside a tty, and a planner's `sb tell parent` reaches
the throwaway lead rather than you. `--all` because a finished planner is dropped from the
default (active-only) status. Watch the row go idle, then read the file it was told to
write.

Hand each planner its case brief by **path**, and hand over the `Brief` section only.
Never the whole case file. The split is a heading, so cutting it is one command:

```
awk '/^## Brief/{on=1;next} /^## Expected signal/{on=0} on' \
    <this directory>/cases/case-1-bounded-work.md > .switchboard/evals/case-1-brief.md
```

Read the file you just wrote before you hand it over. An `awk` that produced an empty file,
or one that caught the wrong half, is a mistake nothing downstream will catch for you.

### 4. The recorded departure every case brief carries

A planner does not present the approval — that is the task owner's, and the task owner in
this exercise is the harness, which cannot read a two-section summary out of a chat pane.
**And nobody answers a block in a throwaway clone**, so a planner that reached for one would
sit there being visible to the machine's supervisor for the rest of the run. So each case
brief departs on one point, on purpose and in writing:

> Write the two-section contract to `<path>` rather than handing it over in words, then
> finish as your instruction says: clear the `planner` field, `sb tell parent "contract at
> <path>"`, `sb done`.

Everything else — the two sections, that format, nothing added, the shape handed back — is
the planner's ordinary instruction and is what is being scored.

**What the departure still costs you.** The approval step is never ticked, so anything a
case expects to see *reopened* cannot be observed at all. Case 5's `progress` condition is
the one that hits, and its file says so.

**What it no longer costs you**, since the planner rewrite: the briefs used to tell a planner
to *stop* rather than to `sb done`, which left every one of them stalled and un-closable by
plain `cleanup`. A planner now finishes by handing the shape back — clear the `planner`
field, tell the parent, `sb done` — so the briefs say that, the agents end cleanly, and the
teardown below is an ordinary `cleanup`. Watch instead for a planner that blocks anyway, or
that presents the contract in chat rather than writing it to the file: either is worth
recording, and neither is what its instruction now says.

### 5. The manifest and the grounding check

```
python3 <this directory>/harness.py manifest <agent> --sb ./bin/sb \
        --brief <path> --tier strong --skills "<what the agent reported>"
python3 <this directory>/harness.py check <plan-id> --sb ./bin/sb
```

**`--tier` is not optional in practice.** The model seed is half of what this pass exists to
check, and no read-only `sb` command reports an agent's tier back — so without it the
manifest reads `tier (not recorded)` and the run has not captured the thing it set out to.
`--skills` is the same story for the self-report below.

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
./bin/sb status --all                                    # read it: every agent, every workspace
./bin/sb cleanup <the lead> --force
./bin/sb workspace close <each workspace the run created> --yes
```

**This is still the step that leaves litter, even though the planners now end cleanly.** The
briefs tell each planner to `sb done`, so plain `cleanup` closes them — but a planner that
departed from its brief and blocked, or one whose turn switchboard gave up on, will refuse,
and `--force` on the lead takes the subtree with it either way. Read `sb status` before and
after rather than assuming. `workspace close` wants `--yes` when
nothing is standing there to confirm. An operator who runs the two bare commands, reads no
error, and walks away leaves five live agents and a worktree behind — it has happened, and
the next pass's spawn is what discovers it.

**Close only the workspaces the run created, by name.** A clone inherits the name of the
workspace it was cloned from, so the clone's own workspace table has a row named after the
LIVE workspace you are standing in. herdr is machine-global: closing that row by name from
inside the clone reaches the live one. Read `./bin/sb workspace list` and close the eval
lead's workspace and its children, nothing else.

Never `herdr workspace close` directly. On a repo's primary checkout it closes every other
herdr workspace sharing that repo's `.git`, and it has taken a whole live fleet down. Never
an unscoped `pkill` either.

Then check `herdr agent list` and the spaces UI, and delete the clone and the
`~/.claude.json` backup. An eval agent left running is the most expensive kind of litter
this pass can leave, and it is invisible from the live fleet's own store.

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
