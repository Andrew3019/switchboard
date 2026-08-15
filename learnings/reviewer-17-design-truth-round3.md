# Round-three adversarial review — is `DESIGN-TRUTH.md` true on `worker-30-review`?

Reviewer: reviewer-17, independent. Read-only: nothing on the branch was changed. Lens:
verify the rewritten `DESIGN-TRUTH.md` sentence by sentence against the code on that
branch — true, complete about what it claims, internally consistent. Not prose, not
structure.

**Verdict: needs changes before this document is trusted — but the changes are to a
handful of sentences, not to the design.** The model it records is real and the code
implements it. Three sentences are false as written, one open question is missing from a
section that now reads as exhaustive, and the rewrite silently invalidated most of the
code's line-number citations into the document.

Method: read `git diff main...worker-30-review`; read `broker.py`, `store.py`, `roles.py`,
`cli.py`, `config.py` and both role prompts at that revision; ran the suite and three
probe scripts in a throwaway `git clone` (torn down). Suite: `1203 passed` in the clone.
"Verified" below means I ran it; "read" means I read the code and did not execute it.

---

## Findings, worst first

### 1. "Only `sb start` ever creates a dispatcher — that is the only path." — false. VERIFIED

> **Only `sb start` ever creates a dispatcher — that is the only path.** Being a top is
> stamped at that moment…

and, in the same section:

> **Only a human may create a dispatcher; `sb start` is refused for agents.**

Both were true when "top orchestrator" named a *stamp*. This branch made `dispatcher` a
*role*, and nothing refuses that role at `sb delegate`. Any agent with delegate rights can
create a dispatcher.

Probe, against the branch's own fake herdr (`tests/test_broker.FakeHerdrAPI`), a `lead`
spawning `--role dispatcher`:

    A) role stored: dispatcher | is_top: 0 | parent: lead1
       got dispatcher prompt: True

So a real dispatcher — the dispatcher prompt, the dispatcher role on its row, in the roles
list every agent is shown — created by an agent, not by `sb start` and not by a human.
What `sb start` uniquely creates is the *stamp*, not the dispatcher.

The codebase already knows this. `defaults/roles/lead.md`'s comment: *"Nothing refuses it,
by the same decision that refuses no other dispatcher behaviour"*, and
`tests/test_roles.py::test_a_lead_is_told_the_dispatcher_role_is_not_one_of_its_options`
says the same in its docstring. The mitigation is one clause in the lead prompt telling a
lead not to. That is a prompt, and the document states it as a fact about the only path
that exists — the exact "intention recorded as prevention" the lens asks for. The same
sentence is in `README.md:27` ("that is the only way one is ever made").

The document is self-consistent about which half the stamp actually decides — *"That
stamp… is what decides where an agent's children land. What an agent may do itself… is the
role it was spawned as"* — which is what makes this sentence wrong: once the role is the
thing that decides what an agent is, "only `sb start` creates one" is a claim about a role
and it is not true.

### 2. The Open section reads as exhaustive and is not. READ

> *…listed here so they are visibly undecided rather than quietly assumed.* … *Both are in
> Product decisions and neither is open. **What follows is.***

What follows is one item, cross-repo dispatch. Whether every level of the tree gets its own
worktree is live with the human (I was told so as context; the document nowhere records it,
open or settled). It sits under sentences that read as settled — *"A lead spawning anything
= new tab in the same exact space"*, *"A worktree belongs to a space, not to an agent"* —
which correctly describe today's code, so a reader takes the question as closed. Before the
rewrite the section said "Nothing open", which at least did not invite the inference that
the list is complete; now it does.

Cost: an agent reading this document to decide whether to raise the question concludes it
was already decided.

### 3. "its home is whatever directory `sb start` was run from" — false, and load-bearing. READ

> This is a dispatcher, and its home is whatever directory `sb start` was run from. —
> confirmed 2026-08-09, the dispatcher's home confirmed 2026-08-14

Two things are wrong. `cli.py:615` sets `repo = store.worktree_root()` — the checkout
*root*, not the directory you typed in — and `Broker._top` passes exactly that as the
workspace's cwd. And `Broker._refuse_outside_main_checkout` refuses `sb start` anywhere but
the repo's pinned main checkout, so the home is not "whatever directory": it is always the
main checkout root. (The literal reading is right only in the one case where the check
gives up: a repo `sb init` never pinned.)

This is load-bearing, which is why it is here rather than in the nits. The grouping entry
argues that a dispatcher is a candidate for herdr's repo group parent *because* its home is
in the repo's folder, and that moving dispatchers out is impossible because `sb start`
cannot separate home from repo. The second half is true and I verified the reason (there is
no flag; `_top` uses `self.repo` for both). The looser sentence at the top weakens the
argument that rests on it, and invites the false idea that a dispatcher's home can be
steered by where you stand.

### 4. The rewrite invalidated ~10 line-number citations into the document. VERIFIED

The codebase cites this document by line range, and the rewrite shifted every range (+6
early, +52 after the roles section) without updating them. Ranges that pointed at the right
entry on `main` and now point at an unrelated one:

| citation | on `main` | on this branch |
|---|---|---|
| `broker.py:3126`, `defaults/prompts.toml:34`, `tests/test_broker.py:397` → 107-110 | "The role list is lightly audited" | the `[sb: from <name>]` prefix entry |
| `broker.py:4539` → 129-133 | "the ping goes to the agent itself" | "How many spaces and agents are alive" |
| `tests/test_roles.py:85` → 142-145 | the five blocking reasons | "Human-facing output is concise" |
| `broker.py:3532`, `broker.py:4324` → 220-224 | `sb done` is when-idle | the `orchestrator`-alias entry |
| `cli.py:153`, `broker.py:116` → 236-247 | the three delivery modes | the Interface section |
| `broker.py:3419`, `cli.py:212`, `tests/test_presets.py:249` → 292-295 | the preset entry (already ~7 off) | the delivery-modes list |

`defaults/roles/lead.md` **was** updated (161-162 → 201-202, and it is correct — I checked
the lines). So the convention is understood and was applied in the one file being renamed
and nowhere else. A few of these (230-234, 292-295) were already drifting before this
branch; most were exact and are now wrong.

Why it matters here rather than as a nit: these citations are how code justifies itself
against the trusted document. A reader following one now lands on an unrelated entry and
concludes either the code or the document is lying.

### 5. "A dispatcher may hand work into a different repo" contradicts the Open entry. READ

Product decisions:

> **Work that belongs in another repo is a question, not a spawn.** A dispatcher may hand
> work into a different repo — but it asks first, and it blocks without starting the task.

Open:

> **Real cross-repo dispatch does not exist and is not close.** The store is per repo, so a
> child in another repo would have no parentage, no messaging, no status, no board row and
> no cleanup reaching it…

The Open entry is true (`store.db_path` hangs off `repo_root`, the shared `.git` — verified
by reading `store.py:46-91`). The dispatcher prompt is blunter still: *"You cannot put an
agent there: every child you spawn forks a worktree of THIS repo."* So "may hand work into
a different repo" describes a permission that no code path can execute — after the ask, the
answer is always that Andrew sets up a dispatcher there himself. A reader taking the first
entry at face value expects a capability behind a confirmation.

I take the sentence to be Andrew's own framing (`tests/test_roles.py` attributes it to him),
so this is a wording problem, not a wrong decision: the two entries need to agree that the
outcome of the ask is a new dispatcher, never a cross-repo spawn.

### 6. "So only the dispatcher ever creates a space" — false; the human's own delegate does too. VERIFIED

`Broker.mints_space` returns True for `HUMAN` and for any caller with no row. Probe:

    mints_space(HUMAN) = True
    human's direct delegate -> workspace: human-child branch: human-child is_top: 0

A human running `sb delegate` in the main checkout mints a space and a worktree with no
dispatcher anywhere. The wording predates this branch (it said "only the top"), but it was
rewritten here and is still wrong.

Related, and pre-existing: *"A lead spawning anything = new tab in the same exact space…
its whole subtree stays in that one space"* is unconditional and `sb delegate --workspace
<other>` breaks it — no role gate on that flag. Verified: a lead's child landed in a
different lead's workspace. Low practical risk; the sentence is still absolute where the
code is not.

### 7. "The mechanism is the `is_top` stamp" — true today, by a coincidence worth naming. READ

> **Dispatcher and lead must be clearly differentiated, and some mechanism other than the
> prompt must make that true as well.** The mechanism is the `is_top` stamp…

The stamp distinguishes *top from non-top*. It does not distinguish *dispatcher-role from
lead-role* — see finding 1, where a stamped-0 agent carries the dispatcher prompt. The two
coincide only because `sb start` is the sole stamper and always spawns
`[vocabulary] main_role`. Set `main_role = "lead"` in a repo's own settings — a supported,
documented override — and they come apart, with the document still claiming a mechanism.

### 8. Two claims in the grouping entry cannot be checked against any code in this repo. READ

> herdr picks one pane already sitting in a repo's folder to serve as that repo's group
> parent… In practice Andrew's own manually opened pane on the repo has always been picked
> first… Nothing breaks functionally; the view is muddled.

herdr is not in this repo, so nothing here supports or refutes any of it, and "has always
been picked first" is an observation about a pick order the entry itself does not claim is
guaranteed. The entry is admirably honest that the model holds by luck; it is worth
labelling the herdr half as observed-not-guaranteed, because the trusted document is read by
agents that cannot check it and this is the one entry where checking is impossible by
construction.

Same class, smaller: *"which Andrew has chosen not to take"* records a human decision the
document gives no way to confirm.

### 9. Smaller, verified

- `broker.py:1289` (new on this branch): *"a workspace is opened by a dispatcher or lead
  delegating into a fork of that name"*. A lead's delegate never forks — `delegate` forks
  only when `inherited and self.mints_space(me)`, and `mints_space` is False for a lead. The
  document is right here and this message is wrong. `cli.py:141` still says "dispatcher",
  correctly.
- `defaults/roles/lead.md` tells every lead *"there is one dispatcher, it is the top of the
  tree"*. The document supports several (*"any other dispatcher's entire tree is
  invisible"*, "one space per dispatcher") and `running_tops`/`live_tops` are written for
  more than one.
- `tests/test_structure.py:50` — the fixture commented "What `sb start` produces" now
  creates `role="lead"`. `sb start` produces `role="dispatcher"`. Harmless to the test,
  misleading as documentation.

---

## What holds up, and was checked

Not a formality — these are the load-bearing claims and they are true.

- **The alias resolves all the way.** *"It survives only as a config alias for `lead`,
  resolving all the way through."* Verified: `--role orchestrator` stores `role=lead`, gets
  the lead prompt, and the identity fragment says `role 'lead'`. `roles.get` returns the
  target Role itself, so board, prompt and row agree — no third answer.
- **The stamp, not the role name, answers "which tops are up".** `store.live_tops` filters
  `is_top=1`; the rename would otherwise have emptied it. The docstring's account of why is
  accurate.
- **`orchestrator` really is gone from what agents read.** I stripped the HTML comments from
  every shipped prompt (`defaults/protocol.md`, all six role files, `house-rules`,
  `adversarial`) and the visible text mentions it nowhere. The retirement is clean where it
  counts.
- **A bare agent's delegate is refused outright** — `_refuse_bare_delegate`, read off the
  role's `delegate` field, and the refusal names the roles that may.
- **A dispatcher's spawn gets its own space and worktree whatever role it carries**, because
  the fork rule reads the stamp. True on the inherited path, which is the only one the
  dispatcher prompt uses; `--workspace` suppresses it, which the entry does not mention.
- **`sb start` cannot separate a dispatcher's home from its repo** — no flag, `_top` uses
  `self.repo` for both. The grouping entry's central constraint is real.
- **The store is per repo**, so the Open entry's account of why cross-repo dispatch is a
  multi-store problem is correct.
- **Unlimited depth** — no depth cap anywhere in `switchboard/`.
- **Enforcement is honestly recorded as rejected.** The Rejected entry says in as many words
  that a well-written prompt is the mechanism, so the dispatcher's behavioural entries are
  not passing themselves off as gates. That is the right shape; finding 1 is wrong because it
  claims a gate that the document elsewhere disclaims.

## Not assessed

- Whether every level should get its own worktree — open with the human; I only note the
  document's silence (finding 2).
- herdr's grouping behaviour — no code here (finding 8).
- Prose, structure, ratification. Dated confirmations were taken at face value except where
  a date labels something the code contradicts.
