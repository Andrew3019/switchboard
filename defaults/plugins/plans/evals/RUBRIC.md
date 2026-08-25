# The judge's instruction

You are scoring a live run of this repo's planner package. Five cases were given to real
plan writers; you were not involved in any of them, and that is the point — you are the
only fresh reader this pass has.

Read `SKILL.md` beside this file for what the pass is. Read the case files in `cases/` in
full, **including** the expected signal at the bottom of each. The planners never saw that
half; you do, because scoring a case against a standard invented after the fact is how an
evaluation certifies itself.

## What you are given, and what you may not ask for

Per case: the context manifest, the brief the planner was handed, the plan it wrote, the
two-section contract it produced, and the harness's grounding report.

You may also read this repo, read-only, to check claims a plan makes about it.

**Do not ask any agent for its reasoning.** Not the planners, not the operator. You score
inputs, outputs, and whatever rationale a planner chose to write into its own plan. A
private-reasoning question is out of bounds for this pass, and an answer to one is not
evidence anybody else can check.

**Do not edit anything.** Not the plans, not the cases, not the rubric, not the repo. Your
output is a report.

## The verdict that matters most

Each case has an **expected signal** committed before the run. Say, per case and in one
word: **met** or **not met**, then why in a sentence or two. That is the headline, and it
is not an average of the five dimensions below — a plan can score decently across the board
and still miss the thing the case was built to detect.

Case 2 is the one to read carefully. It expects the planner to **decline to plan** and to
name the rule it is declining under. A good plan is a failure there.

## The five dimensions

Score each **met / partly met / not met**, with a reason. A reason that could be written
without reading the artifact is not a reason.

### 1. Grounding

Every name the plan uses for a role, model tier, preset, capability, library step or
template exists in the generated catalogue. The harness's `check` output is your evidence
for the structural positions; read the plan's prose yourself for the rest, because the check
does not cover free prose and says so.

`not met` is any invented name. A name that exists but is used for something it is not is
`partly met` — say which.

### 2. Proportionality

Depth matches the work. This is the failure the whole design exists to fix: bounded work
given an hour of process.

**Score it as a contrast across cases and never on one case alone.** Case 1 should be
shorter than case 3 and should carry no `plan-review`; case 2 should carry no plan; case 5
should be case 1 revised, not case 1 rebuilt. If you cannot see the contrast, say the
contrast is absent — that is the finding, and it is a stronger one than any single score.

### 3. Main-agent continuity

Steps are units of work, not agent boundaries. One main agent should own the run of
ordinary steps — implement, test, fix, integrate — and every fresh agent should be
justified by independence, specialization or real parallelism, with the reason stated in
the step's own `strategy`.

`not met` is a fresh agent per step, or a boundary with no reason given. An agent boundary
that is real but unexplained is `partly met`.

### 4. Verification

Each step says how it will be checked, and the check is proportionate to the risk. Look for
verification that could actually fail: "run the tests" on a step that adds no test is a
sentence, not a check. Look also at the plan's termination condition — whether somebody who
was not there could tell from it that the job is finished.

### 5. Invented details

Claims the plan makes **about this repo** that are not true: file paths that do not exist,
commands that do not run, test names that are not there, behaviour the code does not have.
Check them against the repo; you have it.

**Catalogue names are not this dimension.** They are dimension 1, and the harness owns them
mechanically. Keep the two apart or you will double-count one failure and miss the other.

## Drive one case from the runbook

Pick one case and run it end to end from `SKILL.md` alone — the clone, the trust step, the
spawn, the harness commands, the teardown. Not to produce another score: to find out
whether the runbook is followable by somebody who did not write it.

Report every place you had to guess, look elsewhere or ask. Those are defects in the
runbook and they are worth as much as any score here.

## What your report holds

- Per case: **met / not met** on the expected signal, and why.
- Per case: the five dimensions, each **met / partly met / not met**, each with a reason.
- The proportionality contrast across the five, in a short paragraph of its own.
- What you found driving the runbook.
- **What you could not judge, and why.** An evaluation that reports only what it could see
  reads as complete when it is not. Say which artifacts were thin, which claims you could
  not check, and where your own reading is the weakest link.
