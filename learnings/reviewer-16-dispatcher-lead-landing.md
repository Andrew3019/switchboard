# Round-two review: `worker-30-review`, judged as a change landing on a running fleet

Independent reviewer, lens = the moment it lands. Read-only. Branch reviewed at
`109fa8e`. Everything below marked **verified** was run; everything marked **reasoned** was
read but not executed.

**Verdict: needs changes before it lands.** One real defect in the transition
(finding 1), one gap in the evidence that hid it (finding 2), and a mixed-checkout window
that is uncomfortable rather than dangerous (finding 3). The role-resolution half of the
change — the alias — is genuinely well built and I could not break it.

## How I checked

- `git clone /Users/andrew/Code/switchboard` into the scratchpad, `worker-30-review`
  checked out there, a second clone left on `main` for the old-code side. Both torn down.
- Probes driven against the clone's own `switchboard` package plus
  `tests/test_structure.py`'s `Fixture` (fake herdr, temp store). No live store mutated;
  the live store was opened `mode=ro` once, to count rows.
- Suite in the branch clone: `/Users/andrew/anaconda3/bin/python -m pytest tests` →
  **1200 passed in 87s**.

---

## 1. `sb start` stops seeing the top-level agents that are running right now — verified

`Broker.running_tops()` (`switchboard/broker.py:942`) is

    tops = [r["name"] for r in store.live_roots(self.db, MAIN)]

and `store.live_roots` (`switchboard/store.py:1137-1152`) matches `role=?` **exactly**.
`MAIN` is `[vocabulary] main_role`, which this branch changes from `orchestrator` to
`dispatcher` (`defaults/settings.toml:95`).

The live store, read-only
(`/Users/andrew/Code/switchboard/.git/agentflow/state.db`):

    by role:        worker 183, researcher 73, orchestrator 37, reviewer 28,
                    builder 19, qa 15, implementer 5, architect 4
    live roots:     main-15   orchestrator  working  is_top=1
                    board-fix orchestrator  blocked  is_top=1

Both live roots carry the retired role. Probe in the branch clone, one live root with
`role="orchestrator"`, `is_top=1`, and herdr reporting it alive:

    live_roots('dispatcher'):   ['disp-1']
    live_roots('orchestrator'): ['main-15']
    live_roots(MAIN):           ['disp-1']
    running_tops():             []

`running_tops()` is read at `switchboard/cli.py:816`, and it is the only thing that makes
`sb start` print

    still running: board-fix — back to one with: sb start --name board-fix

So the first bare `sb start` after this lands quietly opens a *third* top and says nothing
about the two that already exist — including `board-fix`, which is **blocked**, i.e. the
one waiting on Andrew and the one he most needs the route back to. Nothing errors. The
function's own docstring states the cost exactly: *"omitting a live one costs them the way
back to it."*

`store._MIGRATIONS` / `_backfill_is_top` (`switchboard/store.py:592-617`) is the mechanism
this repo already uses for precisely this shape of problem and it is not used here. I am
not prescribing the fix; I am noting the branch neither migrates the rows nor records a
decision not to.

This is the only place in `switchboard/` that branches on a role *name*. Chased:
`_refuse_bare_delegate` (`broker.py:710`), `restore`'s model lookup (`broker.py:3946`) and
`_resolve_bindings` (`broker.py:2881`) all go through `roles_mod.get()`, which the alias
covers; `status.py:865/1634/1978` only *displays* `row["role"]`; every structural decision
(space, worktree, tree boundary) reads the `is_top` stamp. See "What is well handled".

## 2. The tests pin the rename, not the transition — verified

No test in the suite creates a store row whose `role` is the literal string
`"orchestrator"`. Every one was renamed in lockstep with the code:

- `tests/test_broker.py:2290-2323` — the `running_tops` tests — use the symbol `MAIN`,
  which follows the rename, so they pass identically before and after and can never see
  a legacy row.
- `tests/test_store.py`, `tests/test_status.py`, `tests/test_structure.py` — every
  `role="orchestrator"` became `role="lead"`. The two direct `live_roots(self.db,
  "orchestrator")` assertions in `test_store.py` became `live_roots(self.db, "lead")` — a
  role its one production caller never passes.
- Worst of the set: `TopStampMigrationTest.test_pre_existing_tops_are_stamped_and_nobody_
  else_is` (`tests/test_structure.py:170-196`) is *the* test that models a store written by
  older code, and its legacy `INSERT`s were rewritten from `'orchestrator'` to
  `'dispatcher'`/`'lead'`. It now describes a store that could not have existed before this
  change. The one test looking backwards was pointed forwards.

`tests/test_roles.py` does pin the alias well — `test_the_retired_name_resolves_to_the_
lead_and_not_to_the_fallback` asserts name, delegate and prompt identity. But that is
`roles.get()` in isolation. **What is unproven is that a stored row saying `orchestrator`
still behaves: nothing exercises one, which is exactly why finding 1 survived a green
suite of 1200.**

## 3. Half-applied state: the alias runs one way, and the `sb` on Andrew's PATH is old code — verified

`/Users/andrew/.local/bin/sb` is a symlink to `/Users/andrew/Code/switchboard/bin/sb` —
the **main checkout**, which stays pre-merge while this branch lives in a worktree. Worktree
agents get their own `bin/sb` first on PATH, but `broker.py:346` and `cli.py:517-520`
both document agents falling back to the installed one.

Probe against a clone on `main` (old code) reading rows written by the new vocabulary:

    OLD code knows roles: ['orchestrator','qa','researcher','reviewer','worker']
      get('lead')        -> delegate=False  prompt_len=1009   (the worker fallback)
      get('dispatcher')  -> delegate=False  prompt_len=1009
      get('orchestrator')-> delegate=True   prompt_len=6578
    delegate from a row whose role is 'lead':
      REFUSED: a lead does not spawn agents — only a role with delegate rights does
               (today: orchestrator)...

Two directions, both real while the branch is unmerged:

- A lead spawned by new code, later served by old code (installed `sb`, or a worktree that
  has not taken the branch), **cannot delegate** and is told so in a message naming a role
  that no longer exists.
- `--role lead` typed against old code stores `role='lead'` while the agent in the pane got
  the 1009-char *worker* prompt and no delegate rights. New code then reads that same row
  as a full lead with delegate rights. The row and the pane disagree, and nothing detects
  it.

Not corruption, and it evaporates the moment `main` carries the branch. The alias is
deliberately one-directional — nothing can make old code understand a new name — so this is
inherent to the rename rather than a mistake in it. It is worth knowing that the exposure
window is "however long the branch sits unmerged while agents run", and that Andrew's own
installed `sb` is on the old side of it for that whole window.

## 4. Agents alive at the moment of the change get none of the split — reasoned

Prompts are fixed at spawn; nothing re-briefs a running agent. So `main-15` and `board-fix`
keep the **old orchestrator prompt**, which permits doing a small piece of work itself —
the single thing the new dispatcher prompt forbids unconditionally ("You do none of the
work, and that is unconditional"). Their children converge correctly (a `--role
orchestrator` after landing yields a lead — verified below), so the tree below the top
becomes the new model while the top itself stays the old one. Only a restart makes a top a
dispatcher. That is unavoidable and fine; what is missing is anyone *saying* it — nothing
in the branch, `DESIGN-TRUTH.md` included, notes that adoption of the dispatcher role
requires a fresh `sb start`.

## 5. Documentation — the distinction that matters here

**Agent-facing prompt text is clean, and this was done carefully.** Every remaining
`orchestrator` in `defaults/roles/*.md`, `defaults/protocol.md` and `defaults/prompts.toml`
sits inside an HTML comment (`<!-- ... -->`, stripped by `config.py:62 _COMMENT`) or a TOML
`#` comment. Checked file by file: `qa.md:36`, `researcher.md:26`, `reviewer.md:19`,
`worker.md:38,44`, `lead.md:9,28,30,31` are all between the `<!--` and `-->` markers;
`protocol.md`'s hits are all at lines 34–134 inside its single comment block that closes at
152. **No running agent is told about a role that no longer exists.** That is the part of
this change I tried hardest to break and could not.

Genuinely misleading, as distinct from cosmetically stale:

- `README.md:27,36,76,80` — "A human starts a top orchestrator with `sb start`", while
  `sb start` now prints `dispatcher '<name>' ready`. Human-facing, public, and the first
  thing a new reader matches against what the tool says.
- `defaults/presets/adversarial.md:11,12,32,37,39` — addresses "the orchestrator"
  throughout. This is **printed on demand to an agent that then acts on it**
  (`sb presets adversarial`), and `orchestrator` no longer appears in the roles list any
  agent is given, so a lead reading it has to guess whether the instructions are for it or
  for the dispatcher above it.

Cosmetic only, name them and move on: `defaults/models.toml:40`,
`defaults/settings.toml:70,204,214,362`, `design/*` (history), and
`defaults/plugins/todo/agent.md:6` — the last would be agent-facing, but the todo plugin is
disabled and unbound, so it reaches nobody.

---

## What is well handled — verified

Probes in the branch clone:

    get('orchestrator') -> name='lead' delegate=True model='default' prompt_len=6736
    get('lead')         -> name='lead' delegate=True model='default' prompt_len=6736
    get('dispatcher')   -> name='dispatcher' delegate=True prompt_len=5387
    get('nonsense')     -> name='nonsense' delegate=False prompt_len=1009  (fallback intact)

    a stored row with role='orchestrator' delegating a worker:  -> worker-1, no refusal
      (and its own row keeps role='orchestrator' — the alias reads, it does not rewrite)
    delegate(role="orchestrator") from a top:  -> agent 'lead-1', stored role 'lead'

- **The alias resolves all the way**, exactly as `DESIGN-TRUTH.md:219-221` claims: name,
  prompt, model and delegate rights. `role = r.name` at `broker.py:3057` is taken before
  the name is generated, the presets are bound and the row is written, so prompt, board and
  store agree. The reasoning in `roles.py:88-97` — that a *retired* name must not fall
  through to `fallback_role`, because `worker` cannot delegate and `orchestrator` meant the
  opposite — is right, and the failure it prevents is silent.
- **Everything structural reads the `is_top` stamp, not the role name.** So no existing
  agent's space, worktree, fork behaviour or tree boundary changes. `running_tops` is the
  single role-name read left in the codebase, which is why finding 1 is one finding and not
  a class of them.
- **`_delegating_roles()` (`broker.py:720-727`) generates the refusal text from the role
  table**, so the "today: dispatcher, lead" message is correct with no edit and stays
  correct for a repo that adds its own.
- **`main_name` is untouched.** `sb start` still produces `main-N` and `sb start --name
  main-15` still rejoins the existing agent (`broker.py:971-996`). Andrew's typed commands
  and the names on the board survive the change intact.
- No preset binding was keyed to `orchestrator` in any layer (`defaults/presets.toml`,
  `.switchboard-shared/presets.toml`, `.switchboard/presets.toml`), and `.switchboard/
  roles.toml` declares no role, so nothing silently stops being injected.

## Explicitly not checked

- I did not run a real `sb start`/`sb delegate` against herdr; every behavioural claim
  above comes from the package driven directly with the test suite's fake herdr, plus a
  read-only count of the live store.
- I did not review the `dispatcher` prompt as writing, or the cross-repo rule as policy —
  round one's job, and out of this lens.
- Whether every level should get its own worktree bears on finding 3 only indirectly and is
  the human's open question; I left it alone.
