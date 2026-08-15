# reviewer-18 — `worker-30-review`, read cold as code and tests

Round four, lens: the Python and the configuration that actually runs. Independent; I read
no other round's findings and asked nobody.

**Verdict: good to go.** Nothing here is a reason to hold the branch. Two things I would
want changed before or shortly after it lands (findings 1 and 2), both small, both about
the alias rather than about the split.

Evidence convention below: **RAN** = I executed it and am quoting the result. **READ** = I
reasoned from the source and did not run it.

Isolation: `git clone` of this repo into the session scratchpad, `worker-30-review` checked
out there, everything driven from that clone. Torn down afterwards. I did **not** drive
`./bin/sb` live — no herdr run, no spawn, no store mutation. So every claim below about the
alias and about `live_tops` is from unit-level execution and reading, not from a live spawn.

---

## Findings, worst first

### 1. `roles.get` reads `role_aliases` and `fallback_role` from the SHIPPED settings only — a repo cannot configure either

`switchboard/roles.py:100` and `:103`

```python
alias = config.setting("vocabulary.role_aliases").get(name)
...
fallback = config.setting("vocabulary.fallback_role")
```

Both calls omit `repo=`. `config.setting(dotted, repo=None)` → `config.settings(None)` →
`config.repo_dir(None)` returns `None` → `settings()` returns `_shipped_settings()` and
never merges `<repo>/.switchboard/settings.toml` (`switchboard/config.py:78-87`, `:320-326`).
The role TABLE is repo-scoped (`roles.load(repo)`), the names used to resolve against it
are not.

**RAN**, temp repo with `.switchboard/settings.toml` containing
`role_aliases = { orchestrator = "reviewer", foo = "qa" }`:

```
settings(repo) sees: {'orchestrator': 'reviewer', 'foo': 'qa'}
get(orchestrator) -> lead          # the shipped alias, not the repo's
get(foo) -> foo delegate= False    # repo alias ignored; fell to the worker fallback
```

Consequences:

- The new docstring's closing claim — *"Data, not a literal here, for the same reason every
  other name in this file is (C12)"* — is not true as implemented. It is data, in a file no
  repo can override.
- The pre-existing `fallback_role` line makes the same false promise in as many words:
  *"what an undefined role behaves like is a decision a repo is allowed to make
  differently."* It is not. This diff doubles the untrue claim rather than introducing it.
- `defaults/settings.toml:112`'s note *"Empty it once nothing types the old name"* is true
  only of the shipped file. A downstream repo cannot empty it, and — because `merge` deep-
  merges dicts (`config.py:221-225`) — cannot remove a key even by writing
  `role_aliases = {}`.

Impact on switchboard's own repo today: none, there is no repo-local `role_aliases`. The
failure is silent, which is the serious kind, and it lands on whoever adopts this next.

Fix is one of two, and the choice is a decision, not a defect: pass `repo` down into
`get()` (it already has `self.repo` at every call site in the broker), or delete the two
sentences claiming repo-configurability.

### 2. A dangling alias fails silently in exactly the way the alias exists to prevent — and nothing checks the targets

`switchboard/roles.py:100-102`

```python
if alias and alias in roles:
    return roles[alias]
```

`and alias in roles` is a silent guard. If the target is ever absent — `lead` renamed again,
a repo layer that does not define it — `--role orchestrator` falls straight through to the
worker fallback with `delegate=False`: an agent that cannot spawn anything, for the one name
that used to mean the opposite. That is verbatim the failure the alias was added to prevent,
and it comes back with no message anywhere.

**RAN**, deleting `lead` from the loaded table and resolving:

```
name: orchestrator   delegate: False   prompt: True
```

Nothing guards it. `tests/test_config.py:141`,
`test_the_roles_named_in_settings_all_exist` — the test whose entire stated job is that the
role names in settings resolve — asserts `main_role` and `default_role`/`fallback_role` and
was not extended when `role_aliases` was added. One assertion closes it:

```python
for old, new in config.setting("vocabulary.role_aliases").items():
    self.assertIn(new, roles, f"alias {old} points at a role that does not exist")
```

I would take this one before landing. It is the cheapest test on the branch and it guards
the branch's own mechanism.

### 3. `tests/test_design_truth_refs.py` — keep it, but it is silently partial in its own headline scenario

Judged hard, as asked.

**Stable, not flaky.** Deterministic file reads, no clock, no network, no ordering
dependence. **RAN**: inserting one line at the top of `DESIGN-TRUTH.md` fails it, naming the
offending citation and what the line now reads. It does catch the rot it was written for.

**Its blind spot is bigger than "cannot tell the right entry from the wrong one" makes it
sound.** A citation that slides onto a *different* `**` line passes. **RAN**, simulating
insertions of 1–8 lines above every citation, counting how many of the 13 distinct ranges
would still look valid:

| lines inserted | ranges still passing while pointing at the wrong entry |
|---|---|
| 1 | 0 / 13 |
| 2 | 2 / 13 |
| 3 | 1 / 13 |
| 4 | 2 / 13 |
| 5 | 4 / 13 |
| 6 | 4 / 13 |
| 7 | 1 / 13 |
| 8 | 4 / 13 |

An entry in that document is typically 4–7 lines, so "insert one entry" is squarely in the
range where roughly a third of the citations survive while pointing somewhere else. The
practical hazard is the partial fix: the suite goes red, the editor repairs the ranges the
failure named, the suite goes green, and the ones that landed on a neighbouring entry stay
wrong — the same silent state the test was written to end, now with a passing test over it.
The failure message should say what it cannot check.

**Self-referential.** Line 3 of the test's own docstring cites `DESIGN-TRUTH.md:130-133`,
and `SEARCHED` includes `tests`, so the test's own prose is one of the 25 citations it
enforces. Not wrong, but it means an innocent document edit can fail the test on its own
comment.

**Coverage of where citations may live.** `SEARCHED = ("switchboard", "tests", "defaults",
"acceptance")`. `.switchboard-shared/` (which holds `house-rules.md`, injected into every
agent in this repo) and `notes/` are outside it. **RAN** a repo-wide grep: no numeric
citations live outside `SEARCHED` today, so the coverage is complete as of this commit and
only the future is unguarded.

**Cost to the next person editing the document:** 25 citations across 12 files, updated by
hand, with no helper script. That is the real price of the mechanism, not of this test — the
test only makes the price visible instead of letting it go unpaid. If it ever gets tiresome,
the fix is to cite entries by their bolded phrase rather than by line number; the test then
becomes a substring check that cannot drift at all. That is a design change, not a defect.

### 4. `tests/test_structure.py:52` — the top fixture no longer models a top

```python
def _top(self, name: str = "top") -> str:
    """What `sb start` produces: a bare space over the main checkout, stamped."""
    store.create_agent(self.db, name=name, role="lead", ..., is_top=True)
```

`sb start` produces `role="dispatcher"` (`vocabulary.main_role`, via `Broker.MAIN` at
`broker.py:61`, used at `:1020`). The docstring says the fixture is what `sb start`
produces; it is now what a nested lead looks like with a stamp on it. Nothing in these tests
reads the role, which is exactly why it will stay wrong — it cannot fail. `role=MAIN` there
would keep it honest for free. (`tests/test_broker.py`'s `_dead_top` does use `MAIN` and is
right.)

### 5. Edge input on the alias — exact and case-sensitive

**RAN**, `roles.get` against the shipped table:

```
''              -> ''              delegate False
'Orchestrator'  -> 'Orchestrator'  delegate False
'orchestrator ' -> 'orchestrator ' delegate False
'lead'          -> 'lead'          delegate True
```

The alias exists for muscle memory, and `Orchestrator` is muscle memory. It gets the worker
fallback with no delegate rights, silently — finding 2's failure mode by a different door.
A `.strip().lower()` on the lookup key would cover it; whether that is worth doing is a
judgement, not a defect.

`--role ""` producing `Role(name="")` and then agent names `-1`, `-2` via
`_unique_name` (`broker.py:3339-3343`) is pre-existing and untouched by this diff.

### 6. Stale editor comments that now contradict the branch's own change (comments only)

**RAN**: I flattened all six shipped role prompts, all three shipped presets and
`.switchboard-shared/presets/house-rules.md`, and searched for `orchestrat`. **Zero hits.**
Nothing an agent is ever sent says the word. So this is a maintenance-record issue, not a
live one:

- `defaults/protocol.md:119` (HTML comment): *"`house-rules` … still says this repo's
  default is that the orchestrator integrates."* This diff changed house-rules to say the
  lead integrates. The comment is now a statement about a file that says the opposite.
- `defaults/protocol.md:112` (HTML comment): *"a merge travels down from Andrew through a
  top orchestrator"* — the top is a dispatcher now.
- `defaults/settings.toml:212, 222, 370`, `switchboard/board.py`, `switchboard/status.py`,
  `switchboard/herdr.py`, `switchboard/validate.py`, `switchboard/output.py` and much of
  `broker.py`'s prose still narrate "orchestrator". Most of that is history and reads fine
  as history; the two protocol.md lines above are not history, they are wrong statements
  about the current files.

---

## What is sound, and how I know

- **The rename is complete in everything that ships into a prompt.** **RAN** the flatten of
  every role, every shipped preset and house-rules: no occurrence of "orchestrat" reaches
  any agent. The `{roles}` fragment is still generated from the merged table
  (`broker.py:3135`), so it names `dispatcher, lead, qa, researcher, reviewer, worker` with
  nothing hardcoded.
- **`live_tops` is the right fix and the migration behind it does not break.** `store.py:1172`
  now filters `parent IS NULL AND is_top=1`. The obvious way this could have gone wrong is
  the backfill: if `_backfill_is_top` had identified tops by `role = main_role`, a store
  migrating for the first time *after* the rename would stamp nothing and every historical
  top would vanish. **READ** `store.py:611`: the backfill is
  `WHERE parent IS NULL AND branch IS NULL` — role-independent, so it is unaffected by the
  rename. Correct.
- **Every consumer of a role name resolves through `roles.get`.** **READ**, having grepped
  every reader of a role string: `_refuse_bare_delegate` off the stored row
  (`broker.py:710-711`), `restore`'s tier lookup (`broker.py:3956`), and `delegate`
  normalising once at `broker.py:3063` before the identity fragment, the generated name, the
  preset bindings and the stored row. I found no path left comparing a bare role string
  against a literal, and no path where a stored `orchestrator` gets a different answer from
  a typed one.
- **`role = r.name` is in the right place.** After `_refuse_bare_delegate`, before
  `_unique_name`, before `_say("spawn.identity", ...)` and before `_resolve_bindings`. The
  four things that could have disagreed all read the resolved name.
- **The two new alias tests are behaviour tests, not rename tests.**
  `tests/test_structure.py:315` (`test_a_row_that_still_says_orchestrator_may_still_delegate`)
  covers the load-bearing case — the STORED role, which is the one the whole running fleet
  has — and `:325` pins that the row is filed as `lead`. Both would fail if the feature were
  deleted. `tests/test_store.py:79`
  (`test_live_tops_finds_a_top_stamped_under_the_retired_role_name`) is the regression
  itself, written as the store saw it.
- **All 13 distinct cited ranges point at the right entries.** **RAN**: printed every cited
  range out of `DESIGN-TRUTH.md` and read them against their citing comment. Each one is the
  entry the comment claims. The citation repair in `4bc54d5` is correct, not merely green.
- **Suite green.** **RAN** in the clone: `1205 passed in 95.35s`, matching the stated figure.

## What I did not check

- No live `sb` run: no spawn, no herdr, no pane. The alias is proved at the `roles.get` and
  `Broker.delegate`-with-fake-herdr level only. An end-to-end `--role orchestrator` spawn
  putting a real lead prompt into a real pane is **unproven** by me.
- `acceptance/accept.py`'s `--role lead` change is **unrun** — the acceptance harness needs a
  live fleet. It is a one-word change to a role that exists and can delegate, which is all I
  can say for it.
- I did not review the prose of the two role prompts or of `DESIGN-TRUTH.md`; out of bounds
  for this lens, and three rounds have covered it.
