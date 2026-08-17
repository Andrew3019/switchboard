# Analyse switchboard usage

Run this every so often — after a batch of jobs, at the end of a week, whenever somebody
wonders what the catalogue should hold. It reads the plan records that switchboard keeps
forever and says what should become a new step, template, preset, role, optimisation or
piece of tooling. It is what saving the records buys.

Each run reads the records **cold**. Nothing is carried between runs, no state is kept, and
running it twice in a row is not an error — it is the same corpus read again, plus whatever
has happened since.

## The hard rule

**Propose only. Never edit.** Nothing in this pass writes to `plans.json`, to a plan, to
`library/`, to `templates/`, to `presets.toml`, to a preset file or to a role file. Not "ask
first" — do not. The output of this pass is a message: what you would add, why, and the plan
ids the claim rests on. Somebody else decides, and the catalogue is edited in an editor by a
person.

Concretely, for the whole of this pass: no `sb plugin plans` verb but `list`, `show`,
`changelog`, `library` and `template list`. No `tick`, `skip`, `note`, `rework`, `add-step`,
`name-step`, `dep`, `assign`, `checkpoint`, `create` or `template use` — not even on a plan
you own, not even to "record that the analysis ran". No `Write`, no `Edit`, no `git commit`.

## Running it

```
python3 <this directory>/evidence.py            # the report
python3 <this directory>/evidence.py --json     # the same survey, structured
```

`evidence.py` shells out to `sb plugin plans list --all --json` — the plugin's own read
surface, so it cannot drift from the real format and it gets the resolved library names, the
derived condition and the live worktree reading for free. It runs no other command; that
argv is a constant in the file. To analyse a corpus captured elsewhere, or one you were
handed:

```
sb plugin plans list --all --json > /tmp/corpus.json
python3 <this directory>/evidence.py --input /tmp/corpus.json
```

It counts. It does not judge. Your job is the judging: read the report, read the plans it
cites, and decide which candidates are worth putting to a human.

## Reading the report

**Abandoned plans come first, and they come first on purpose.** A plan whose worktree is
gone with steps still open is a job that fell apart, not a job that finished. If you read
them as successes you will propose promoting whatever the derailed job happened to do. Read
them for what went wrong; never count them as evidence that something worked. `evidence.py`
marks any proposal supported only by abandoned or unreadable plans as `weak` — take that
seriously rather than arguing it up.

**The two kinds of rework are different signals and are never added together.**

- *Rework as try count* — a `rework` entry in the changelog. The step was re-entered, the
  plan's shape did not change. The lead had the right steps and something about how the step
  is *run* is wrong. That is a preset, a tighter brief, a better tool, an optimisation.
- *Rework as added step* — an `add-step` entry. The plan's shape changed mid-job. Something
  was missing from the plan, and if the same thing keeps being added, it is missing from the
  catalogue or from the template. That is a new step or a template change.

Both live in the changelog and the report reads them from there, from the action, not from
guessing at the step. If an entry has no reason on it, you cannot tell a step added for
rework from one that was simply forgotten — say so and do not pick one.

A step whose `tries` is above 1 with no `rework` entry behind it is neither: the record was
edited outside the verbs. Report it, count it as nothing.

**Freehand step names barely compare.** Granularity is a lead's judgement, so two leads
splitting one job into three coarse steps and twelve fine ones produce records that count
differently. Library steps are the part that genuinely compares, because a name means the
same thing wherever it appears. Weight your proposals accordingly, and read the plans before
promoting a name on the strength of a string match.

## Saying it

Every output of this pass — the message you send, the note you leave, anything a human
reads — names the bias:

> The record is biased toward jobs that went well. Ticking and note-writing are voluntary
> acts by an agent still on top of its job, so a run that derailed is thin or absent here.
> Absence of a pattern is not evidence it does not recur.

`evidence.py` puts that at the top and the bottom of its report and in the JSON, so quoting
it is not extra work. Do not drop it because it was in last week's output too; a reader
seeing one of these for the first time is who it is for.

Then, per proposal:

- **What** to add, and which kind it is — step, template, preset, role, tooling, optimisation.
- **Why**, in one sentence about the jobs, not about the counts.
- **Which plans** it came from, by id, with their condition. A claim of "5 times" cannot be
  checked; `p-3 (finished), p-7 (finished)` can.
- **What would weaken it** — the abandoned ones behind it, the missing reasons, the freehand
  names that may not be the same step at all.

Propose nothing when nothing recurs. An empty pass that says "the corpus is three plans and
one of them was abandoned; nothing recurs yet" is a correct run, and inventing a proposal to
have one is the failure mode this whole pass is exposed to.

## What the record does not carry

If the analysis wants something the record does not have, say so in the output. Do **not**
add a field: the plan schema belongs to the verbs that write it, and a pass that grew the
record would be editing it. Known ones the report will raise on its own: plans with no notes
at all, rework and add-step entries with no reason, and try counts with no verb behind them.

Two more that the report cannot raise, because they are about the shape of the record rather
than about one job:

- **A changelog entry does not carry the step it is about as a field.** It is inside
  `detail`, which every verb happens to open with the id. The rework split depends on
  reading it back out of a rendered string.
- **The record carries an owner's name and never its role.** So "leads keep doing X" and
  "workers keep doing X" are not questions this corpus can answer, and a proposal about
  roles rests on you knowing who those agents were.
