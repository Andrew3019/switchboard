# Proposal: split the orchestrator role, and what to call the pieces

Proposal only. No source or prompt files touched. Written by researcher-21, based on
reading `switchboard/{broker,store,roles,cli}.py`, `defaults/roles/orchestrator.md`,
`defaults/settings.toml`, `defaults/prompts.toml`, and `DESIGN-TRUTH.md`.

## 1. The two jobs, in plain words

**Today** there is one role, `orchestrator`, used at every depth — `sb start`'s top agent,
a workspace lead spawned off it, and any further sub-orchestrator a lead spawns for a
sub-job all get the exact same prompt (`defaults/roles/orchestrator.md`), because the
file's own header says the difference is "only scope, and scope is already told to it at
spawn." Andrew has now concluded that was wrong for the top specifically.

**What actually differs, concretely:**

- **Where it lives.** The top gets a *new* space and worktree, always — it's the only
  thing `sb start` ever makes, and only a human can call `sb start`
  (`switchboard/cli.py:802-812`, DESIGN-TRUTH.md:49). Everything nested — a lead, or a
  lead's own sub-lead — lands as a tab inside the *caller's* existing space
  (`switchboard/broker.py:3069-3097`, "THE FORK RULE"). This is already a hard,
  code-enforced fact, not a prompt convention — see §3.
- **What it holds.** A lead owns one multi-step task end to end: it holds context on that
  task, plans it, splits it, runs children in its own worktree, and is the thing a human
  or parent actually talks to while the work is happening. The top, per Andrew's framing,
  should hold none of that — its whole job is to take whatever lands on it, including a
  one-line question, and hand it to a child in a fresh worktree, so that every follow-up
  continues with *that child*, not with the top itself.
- **What it does when idle.** DESIGN-TRUTH.md:68-69: "The top orchestrator is just idle.
  It should not be monitoring. It persists until Andrew closes it." A lead is never
  idle in that sense — while its task is open it is either working, waiting on a child, or
  blocked; it reports done or blocks when its task resolves (DESIGN-TRUTH.md:71-80).
- **What it cleans up.** A lead cleans up its own children before it reports
  (DESIGN-TRUTH.md:75-76, `defaults/roles/orchestrator.md:171-180`). The top has no
  children to clean in that sense — the thing under it *is* the lead, and cleaning the top
  itself is a human's call (`sb cleanup` from the board), not a rule the top's own prompt
  needs to carry.
- **Who it reports to.** A lead's reader is "your parent, in virtually every case"
  (`defaults/roles/orchestrator.md:184`) — true today because a sub-orchestrator's parent
  is another orchestrator or a lead. The top's parent is definitionally the human: nothing
  else can spawn one (DESIGN-TRUTH.md:49). Its whole "what you say" section is currently
  written for an agent with a parent that reads summaries — wrong audience for the top,
  whose only reader is the person watching the board.

**What does NOT differ** (so it does not belong in a "why split" argument): both may
delegate; both use `sb block`/`sb tell`/`sb done` identically; both share the protocol
text; the file-ownership and re-plan discipline is only ever a lead's problem in practice
(the top does no writes — DESIGN-TRUTH.md:884), so it's not a counterexample, it's a
section the top's prompt simply doesn't need.

**The one real difference that justifies splitting into two prompts, not two sections of
one prompt:** the top holds no task and no context by design, while a lead's entire job
is to hold exactly that. Every other difference above is a consequence of this one. A
single prompt has to say "hold context and plan, unless you're the top, in which case
don't" — which is exactly the kind of conditional instruction that gets read selectively
and ignored under load. Two short prompts, one for each stance, is more reliable than one
prompt with a branch in it.

## 2. Vocabulary proposal

**Recommendation: retire `orchestrator`. Top-level role → `dispatcher`. Nested,
task-owning role → `lead`.**

- `lead` is not a new word for Andrew to learn — he already uses it himself,
  DESIGN-TRUTH.md:40: "it gets an orchestrator with it, and that agent can be called
  `<name>-lead`." Naming the *role* what he already names the *agent* costs him nothing.
- `dispatcher` names exactly what the job does now (take a task, hand it to a child) and
  nothing it used to do (hold a plan, monitor, synthesize). Keeping `orchestrator` for
  this role, out of inertia, would leave a word that means "coordinates many parts" on a
  role whose defining trait is now "holds nothing" — the same one-word-two-jobs confusion
  Andrew is trying to remove, just relocated instead of removed.
- Both read as plain English on the board and in `--role`, with nothing to translate.

**Alternative: keep `orchestrator` for the top, rename only the nested role to `lead`.**
This is the lower-churn option — `DESIGN-TRUTH.md` already says "top orchestrator" or
"top-level orchestrator" upwards of 30 times, and every one of those sentences stays
literally true without an edit. The decision between the two options comes down to one
question, and it's Andrew's to answer, not mine: does he want the *word* "orchestrator"
to survive attached to a smaller job than it used to describe, or does he want it gone
because it was always a description of the union of both jobs and neither job alone is
"orchestrating" anymore? I lean toward retiring it (my recommendation above) because the
top's new job description — hold no context, delegate the very first task it gets — reads
to me as the opposite of what "orchestrate" suggests, and a word that means the opposite
of what it's attached to is worse than a new word.

Either way: **`lead` for the nested role is not in question** — it's already Andrew's own
term, it's unambiguous, and it correctly covers every nested case (a workspace lead, and
any further sub-lead one of those spawns for a sub-job — DESIGN-TRUTH.md's "an
orchestrator spawning anything = new tab in the same exact space" already treats those
uniformly, so one role name for all of them is consistent with how the system already
behaves, not a new distinction being invented).

## 3. Blast radius of a rename

**The good news, found by reading the spawn path, not assumed:** the fork/no-fork
decision that actually makes a top different from everything nested is **already** driven
by a boolean column, not by the role string. `switchboard/broker.py:3097`:
`if inherited and self.mints_space(me):` — `mints_space` reads `agents.is_top`
(`switchboard/store.py:158`, stamped only by `_top`/`sb start`,
`switchboard/broker.py:1012-1020`). `role` (`switchboard/store.py:143`, free TEXT) plays
no part in that decision. **This means a rename is a vocabulary and prompt change, not a
behavior change** — nothing about how spawns fork, board width
(`switchboard/broker.py:3224-3227`), or scope currently keys off the literal string
`"orchestrator"`. I grepped every hit of that string across `switchboard/*.py`
(`board.py`, `broker.py`, `cli.py`, `herdr.py`, `output.py`, `presets.py`, `status.py`,
`store.py`, `validate.py`) and every one is a comment, docstring, or a human-facing
string literal — none is an `if role == "orchestrator"` check. Roles are explicitly data
(`switchboard/roles.py:1-17`, "Vocabulary is data (C12)"), which is exactly why this is
possible.

**What a rename actually touches:**

- **Role registry / files.**
  - `defaults/roles/orchestrator.md` — the shipped prompt. To split, this becomes two
    files: e.g. `defaults/roles/dispatcher.md` (short, the "hold no context, delegate the
    first thing" prompt) and `defaults/roles/lead.md` (the bulk of the current file's
    content — planning, file ownership, cleanup, synthesis, all of which is a lead's job
    already). This is the one substantial rewrite, and it's prompt text — explicitly out
    of scope for this pass, left for whoever implements the split.
  - `defaults/settings.toml:94` — `main_role = "orchestrator"` becomes
    `main_role = "dispatcher"` (or stays `"orchestrator"` under the alternative). One
    line.
  - `.switchboard/roles.toml` — this repo's own override layer. It currently sets nothing
    (empty on purpose, per its own header comment) so nothing to change here, but its
    header comment narrates the old `builder`/`qa` history using role names as examples —
    worth a read-through, not an edit, since it's explanatory prose about a past mistake,
    not about `orchestrator` itself.
- **Prompt text that names roles.** `defaults/prompts.toml:49` — the `roles` fragment
  ("The roles that exist are: {roles}...") is **already generated from the live role
  table** (`switchboard/broker.py:3125`, `roles=", ".join(sorted(self.roles))`), so it
  needs no edit — it will say the new names automatically once the role files are
  renamed. `defaults/prompts.toml:32` (`identity`) is templated on `{role}`, also no edit.
  I did not find any prompt string that hardcodes the word "orchestrator" as opposed to
  referring to it in a comment — `start_task` (`prompts.toml:76`) and `child_done`
  (`prompts.toml:99`) are both role-name-agnostic in their actual text.
- **CLI help and error strings — hand-written, need editing.**
  `switchboard/cli.py:104` (`help="start a top-level orchestrator..."`),
  `cli.py:141` (`--workspace` help text, "a workspace is opened by a top orchestrator
  delegating"), `cli.py:809` (refusal message when an agent calls `sb start`), `cli.py:820`
  (`sb start`'s own success message, `f"orchestrator '{name}' ready in its own
  workspace..."`). Four short literal-string edits.
- **Stored role values on existing agent rows.** `agents.role` is `TEXT NOT NULL`
  (`store.py:143`), and nothing in the read path re-resolves an old row's role against the
  current role table except at **spawn time**, to build that agent's prompt
  (`roles.get()` is called from `Broker.delegate`, `broker.py:3053`, not from anywhere
  that reads an existing row later). A currently-running agent whose row says
  `role="orchestrator"` keeps running exactly as it does today — its prompt was already
  baked in when it was spawned. **Nothing needs migrating for correctness.** The only
  place old rows would look odd is display: `sb board`/`sb status` would show a role label
  (`orchestrator`) that is no longer in the live role list. That's cosmetic, not
  functional, and self-heals as those agents finish and close.
- **`--role` argument.** `cli.py:132` (`d.add_argument("--role", default=...)`) takes
  free text validated only as a token (`cli.py:344`, length + shape, not membership) — no
  code change needed there; it already accepts any string, which is what makes an
  "unknown role" edge case (§4) possible in the first place.
- **Tests.** `role="orchestrator"` or the bare string appears roughly 180+ times across
  `tests/test_broker.py` (79), `tests/test_workspace.py` (40), `tests/test_structure.py`
  (19), `tests/test_store.py` (17), `tests/test_status.py` (15), plus smaller hits in
  `test_roles.py`, `test_config.py`, `test_workspace_list.py`, `test_board.py`,
  `test_presets.py`, `test_shipped_plugins.py`. Nearly all of these use `"orchestrator"`
  purely as a stand-in for "an agent that can delegate" — a mechanical find-and-replace to
  the new name(s), not a logic change, but wide enough that whoever implements this should
  budget for it as real, if boring, work. `tests/test_roles.py:137` specifically asserts
  on `roles.load(self.repo)["orchestrator"].prompt` and would need to target whichever new
  name(s) replace it.
- **Docs, research notes, design history.** `README.md`, `DESIGN-TRUTH.md` (not to be
  edited by me — see below), `defaults/README.md`, everything under `design/`,
  `research/`, `reference/`, `notes/` (excluding this file) — 20+ files mention
  "orchestrator" in prose. Not code, no functional risk, but a rename that ships without
  touching these leaves the docs describing a role that no longer exists.

**What I would NOT touch, and why:** `DESIGN-TRUTH.md` itself. Per its own rules only
Andrew edits it. If he adopts this proposal, its "Orchestrators" section
(lines 150-174) and every "top orchestrator" / "top-level orchestrator" sentence
throughout would need his own pass to either keep "orchestrator" (alternative option) or
retire it in favor of "dispatcher" (recommendation) — I'm flagging that staleness, not
fixing it.

## 4. Edge cases, each with a recommendation

- **An existing long-running agent whose stored `role` no longer exists** (e.g. it was
  spawned as `orchestrator` before a rename retires that name). As shown in §3 this is
  harmless in practice — its prompt is already baked in — but its board label goes stale.
  **Recommendation:** do nothing special for the row itself (no migration needed); accept
  the cosmetic mismatch as self-resolving once the agent closes. Do not write a migration
  that rewrites old `role` values — `role` is also a historical record of what an agent
  actually was when spawned, and rewriting it after the fact would falsify that record for
  no functional gain.
- **Someone types the old name** (`sb delegate "..." --role orchestrator` out of muscle
  memory, after the role file is deleted). This is the sharpest edge case I found. Today,
  `roles.get()` (`switchboard/roles.py:82-94`) makes an unrecognized role silently inherit
  the **fallback role's fields** — and `fallback_role = "worker"`
  (`defaults/settings.toml:105`), whose `delegate` defaults to `False`
  (`switchboard/roles.py:41,48-50`). So a stale `--role orchestrator` after retirement
  would silently spawn an agent that **cannot delegate**, with no error — exactly the
  "role nobody thought about is a leaf" default the comment at `roles.py:48-50` describes,
  but landing on someone who typed a name that used to mean the opposite. **Recommendation:**
  keep a thin `defaults/roles/orchestrator.md` alias for a deprecation window — same
  `delegate = true`, a one-line prompt that says "you were spawned as `orchestrator`,
  which is now called `lead`/`dispatcher`; behave as that role" — rather than deleting the
  file outright. Retire it for real only after checking nothing still spawns it by that
  name.
- **A role name typed that was never in the list at all** (today: silent inherit of
  `fallback_role`, keeping its own display name — `roles.py:82-94`). The task asks whether
  that's still right given the split. I think yes, unchanged: this is the mechanism that
  lets `sb delegate --role archaeologist` work without anyone pre-declaring it, which is a
  deliberate, documented feature (`roles.py:83-84`, `.switchboard/roles.toml`'s own header
  calls this out as the intended trap-avoidance). The split doesn't change the case for
  it. The only new wrinkle is the previous bullet — an old *known* name going stale is a
  different situation from a name that was *never* known, and deserves the alias
  treatment above rather than folding it into ordinary fallback behavior.
- **A lead that spawns a lead.** Already how the system behaves today, uniformly: DESIGN-
  TRUTH.md's fork rule treats "an orchestrator spawning anything" as "a tab in the same
  space" regardless of depth, and `mints_space` keys only on `is_top`
  (`broker.py:3097`, `store.py:158-171`). Under the split this is unchanged and, I'd
  argue, gets *clearer*: every such spawn is a `lead` spawning another `lead`, with no
  special case, since `is_top` is what marks the one exception (the top itself) and
  nothing else is exceptional. **Recommendation:** no code change needed here; worth a
  sentence in the `lead` prompt saying explicitly that a sub-lead it spawns is a `lead`
  too, not a diminished version of one — the current `orchestrator.md:157` already makes
  this point ("A sub-orchestrator is an orchestrator in its own right") and it should
  carry over.
- **Should the top-level role even be spawnable by anything other than a human?** Already
  answered, and already enforced in code, not just prompt: `switchboard/cli.py:802-812`
  refuses `sb start` for any caller `_agent_caller()` identifies as an agent, citing
  DESIGN-TRUTH.md confirmed 2026-08-11. **Recommendation:** leave this exactly as is — it's
  the one piece of "hard tool-layer enforcement" that already exists for this role
  specifically, it predates and is orthogonal to this rename, and nothing about the
  rename should touch it. Worth noting for completeness since the task's framing
  ("no hard tool-layer enforcement" for the rest of the split) could otherwise be
  misread as applying here too — it doesn't; this particular restriction is not part of
  what's being proposed, it's pre-existing.

One more thing worth putting in front of Andrew explicitly, since it's exactly the kind of
thing DESIGN-TRUTH.md exists to prevent silently drifting: its own "Open / undecided"
section (lines 338-346) currently reads "*Nothing open. The one item here — the mechanism
distinguishing top from workspace orchestrators — was answered on 2026-08-09 ... `sb
start` is the only path that creates a top, and `sb delegate` branches on that stamp.*"
That closed the question of what makes them behave differently (the `is_top` stamp).
This proposal is a different, newer question — what they should be *called*, and whether
they should read as one job's two prompts or two named things — and isn't in tension with
that entry, but it does mean the entry stops being the last word on this topic once (if)
this ships, and Andrew's own consistency pass should probably note that explicitly rather
than leave the two looking unrelated.

## 5. Change list for whoever implements this

Rough size: **small in code, small-but-wide in tests, one real writing task.**

1. **Write two role prompts** (the real work): split
   `defaults/roles/orchestrator.md` into `defaults/roles/dispatcher.md` (short — hold no
   context, delegate the first task, no plan/cleanup/synthesis sections) and
   `defaults/roles/lead.md` (the current file's body, almost unchanged — it already
   describes a task-owning, worktree-holding, cleans-up-after-itself agent). This is
   the thing I'm least sure of scoping tightly: the current file's six-failure retrospective
   (comment block, lines 6-122) is all *lead* material and should probably move wholesale;
   I did not attempt to draft either new prompt since prompt edits are out of scope for
   this pass.
2. **`defaults/settings.toml:94`** — flip `main_role` to the new top-level name.
3. **`switchboard/cli.py`** — edit the four literal strings at lines 104, 141, 809, 820.
4. **Decide the alias question (§4)** — ship a thin back-compat `orchestrator.md` or not;
   my recommendation is yes, temporarily.
5. **Tests** — mechanical rename of `role="orchestrator"` fixtures across the ~10 files
   listed in §3; `tests/test_roles.py:137` needs its target key updated to match whichever
   new file(s) carry the prompt content being asserted on.
6. **Docs** — README.md, defaults/README.md, design/*, research/*, reference/* prose
   mentions; not urgent, not functional, but real staleness if skipped.
7. **DESIGN-TRUTH.md** — not mine to touch; flag to Andrew that adopting this proposal
   makes its "Orchestrators" section (150-174) and ~30 other "top orchestrator" mentions
   describe a retired or repurposed word, and it needs his own consistency pass either way.

What I'm unsure of, flagged rather than guessed: exactly how much of the current
`orchestrator.md` retrospective commentary (the six-failure analysis) is lead-specific
versus still relevant to the dispatcher's much smaller prompt — I'd guess almost all of
it is lead-specific (it's about planning, fan-out, and synthesis, none of which a
context-free dispatcher does), but I did not draft the dispatcher prompt to check that
claim, since drafting prompts was explicitly out of scope here.
